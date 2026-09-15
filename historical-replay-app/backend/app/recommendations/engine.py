"""Compare physical plans and explicit commercial assumptions; no LLM arithmetic.

Every proposal inserts one vessel into an immutable receiving reservation ledger.
These are independent what-ifs, not a jointly reserved or approved schedule.
"""
import copy
import math
from datetime import timedelta

from app.errors import DomainError
from app.optimisation.engine import conflicts, fixed_options
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, TAIL, yard_trace
from app.optimisation.validation import validate_schedule
from app.synthetic.simulator import parse, stamp

ENGINE_VERSION = 'responsible-routing-v1'


def hours(delta):
    return delta.total_seconds()/3600


def rejected(action, terminal_id=None, *codes, **evidence):
    return dict(action=action, terminal_id=terminal_id, feasible=False, eligible=False,
        rejection_codes=list(codes), evidence=evidence, outcome=None, expected_hours_saved=None,
        conservative_hours_saved=None, estimated_cost_change_usd=None,
        estimated_emissions_change_tonnes=None, estimated_net_benefit_usd=None)


def impact(current, alternative, policy, action):
    saved = hours(parse(current['expected_delivery'])-parse(alternative['expected_delivery']))
    cost = alternative['total_cost_usd']-current['total_cost_usd']
    co2 = alternative['total_co2_tonnes']-current['total_co2_tonnes']
    # Correlation is unknown: subtract both uncertainty radii for diversions.
    uncertainty = current['uncertainty_hours']+alternative['uncertainty_hours']
    conservative = saved-uncertainty
    benefit = saved*policy.time_value_usd_per_hour-cost-co2*policy.carbon_value_usd_per_tonne
    benefit -= uncertainty*policy.uncertainty_cost_usd_per_hour
    codes = []
    if benefit <= policy.minimum_net_benefit_usd:
        codes.append('INSUFFICIENT_END_TO_END_BENEFIT')
    if alternative['deadline_lateness_hours'] > current['deadline_lateness_hours']+1e-7 or alternative['deadline_worst_lateness_hours'] > current['deadline_worst_lateness_hours']+1e-7:
        codes.append('CUSTOMER_DEADLINE_RISK_INCREASES')
    if action in ('ALTERNATE_TERMINAL', 'ALTERNATE_PORT'):
        if saved < policy.minimum_diversion_hours_saved:
            codes.append('INSUFFICIENT_DELIVERY_TIME_SAVING')
        if conservative < policy.minimum_conservative_hours_saved:
            codes.append('UNCERTAINTY_ERASES_DIVERSION_BENEFIT')
    elif saved < -1e-7:
        codes.append('DELIVERY_WOULD_BE_LATER')
    return dict(expected_hours_saved=round(saved, 6), conservative_hours_saved=round(conservative, 6),
        estimated_cost_change_usd=round(cost, 6), estimated_emissions_change_tonnes=round(co2, 6),
        estimated_net_benefit_usd=round(benefit, 6)), codes


class RecommendationEngine:
    def __init__(self, data, assignments, policy, voyages, tariffs, model_version,
                 yard_capacities=None, source_gate_plan=None):
        self.original = prepare(data)
        self.policy, self.model_version = policy, model_version
        self.voyages = {v.call_id: v for v in voyages}
        self.tariffs = {t.terminal_id: t for t in tariffs}
        source = Resources(self.original)
        validate_schedule(self.original, assignments, gate_plan=source_gate_plan)
        self.data = copy.deepcopy(self.original)
        self.data['optimisation_policy']['allow_rerouting'] = True
        self.data['_recommendation_terminal_switch'] = True
        self.data['_certified_yard_capacities'] = yard_capacities or source.planning_capacity
        self.r = Resources(self.data)
        self.assignments = {a['call_id']: a for a in assignments}
        self.options = [self.internal(a) for a in assignments]
        frozen, _, failures = fixed_options(self.r)
        if failures:
            raise DomainError('SOURCE_RESERVATION_UNAVAILABLE', failures[0]['message'])
        self.options.extend(o for o in frozen if o['call_id'] not in self.assignments)
        self.fixed = {c['call_id'] for c in self.original['carry_in']} | {
            c['call_id'] for c in self.original['commitments']}

    def internal(self, a):
        return dict(call_id=a['call_id'], berth_id=a['berth_id'],
            start_slot=round(hours(parse(a['start'])-self.r.origin)*4),
            completion_slot=round(hours(parse(a['completion_time'])-self.r.origin)*4),
            end_slot=round(hours(parse(a['end'])-self.r.origin)*4),
            planned_moves=a['planned_moves'], waiting_minutes=a['waiting_minutes'],
            crane_ids=a['crane_ids'], execution_profile=a['execution_profile'])

    def uncertainty(self, call, tid, voyage, tariff):
        risk = self.data.get('prediction_risk', {}).get(call['id'])
        radius = max(risk['prediction']-risk['lower'], risk['upper']-risk['prediction']) if risk else self.policy.uncertainty_fallback_hours
        # A destination prior is evidence of risk, not a new vessel-specific ML prediction.
        destination = [v for cid, v in self.data.get('prediction_risk', {}).items()
                       if cid in self.r.calls and self.r.calls[cid]['terminal_id'] == tid and cid != call['id']]
        if tid != call['terminal_id']:
            radius = max(radius, max((max(v['prediction']-v['lower'], v['upper']-v['prediction']) for v in destination),
                                     default=self.policy.uncertainty_fallback_hours))
        return radius+voyage.eta_uncertainty_hours+tariff.inland_uncertainty_hours, risk

    def remaining_distance(self, voyage):
        # Propagate a recent position to the logical planning origin using the
        # declared speed. Never apply a speed adjustment retrospectively.
        elapsed = max(0, hours(self.r.origin-voyage.position_as_of))
        return max(0, voyage.remaining_distance_nm-elapsed*voyage.planned_speed_knots)

    def outcome(self, original_call, option, arrival, speed, distance, voyage, capacity_checked=True):
        tid = self.r.berths[option['berth_id']]['terminal_id']
        tariff = self.tariffs[tid]
        p = self.policy
        depart = self.r.times[option['end_slot']]
        start = self.r.times[option['start_slot']]
        wait = max(0, hours(start-arrival))
        radius, risk = self.uncertainty(original_call, tid, voyage, tariff)
        delivery = depart+timedelta(hours=tariff.inland_hours)
        physical_lower = arrival+timedelta(hours=(option['end_slot']-option['start_slot'])/4+tariff.inland_hours)
        # Speed-law proxy: hourly fuel ~ speed^3, fuel per nautical mile ~ speed^2.
        scale = min(2.5, max(.3, self.r.vessels[original_call['vessel_id']].get('capacity_teu', 10000)/10000))
        base_distance = 0 if original_call['id'] in self.r.arrivals else self.remaining_distance(voyage)
        sailing_fuel = base_distance*p.reference_fuel_tonnes_per_nm*(speed/p.reference_speed_knots)**2*scale
        # Alternate port is a conservative route via the original port, never
        # a claimed straight-line vessel-position shortcut. Diversion leg uses
        # the optimiser's documented transit speed.
        diversion_speed = self.r.policy.transit_speed_knots if self.r.terminals[tid]['port_id'] != self.r.terminals[original_call['terminal_id']]['port_id'] else speed
        sailing_fuel += distance*p.reference_fuel_tonnes_per_nm*(diversion_speed/p.reference_speed_knots)**2*scale
        waiting_fuel = wait*p.anchorage_fuel_tonnes_per_hour*scale
        moves = original_call['unload_moves']+original_call['load_moves']
        teu = moves*original_call['teu_per_move']
        costs = dict(sailing_fuel=sailing_fuel*p.fuel_price_usd_per_tonne,
            waiting_fuel=waiting_fuel*p.fuel_price_usd_per_tonne,
            port_call=tariff.port_call_usd, handling=moves*tariff.handling_usd_per_move,
            inland=teu*tariff.inland_usd_per_teu)
        emissions = dict(sailing=sailing_fuel*p.co2_tonnes_per_fuel_tonne,
            waiting=waiting_fuel*p.co2_tonnes_per_fuel_tonne,
            handling=moves*tariff.handling_co2_tonnes_per_move, inland=teu*tariff.inland_co2_tonnes_per_teu)
        sailing = base_distance/speed+distance/diversion_speed
        return dict(terminal_id=tid, berth_id=option['berth_id'], arrival=stamp(arrival), berth_start=stamp(start),
            service_completion=stamp(self.r.times[option['completion_slot']]), departure=stamp(depart),
            expected_delivery=stamp(delivery), delivery_lower=stamp(max(physical_lower, delivery-timedelta(hours=radius))),
            delivery_upper=stamp(delivery+timedelta(hours=radius)), planned_wait_hours=round(wait, 6),
            raw_model_wait_hours=risk['prediction'] if risk else None,
            wait_lower_hours=round(max(0, wait-radius), 6), wait_upper_hours=round(wait+radius, 6),
            waiting_basis='conditional_executable_schedule; raw_model_prediction_is_risk_evidence',
            sailing_hours=round(sailing, 6), sailing_difference_hours=round(sailing-base_distance/voyage.planned_speed_knots, 6),
            diversion_distance_nm=round(distance, 6), speed_knots=speed,
            total_cost_usd=round(sum(costs.values()), 6), total_co2_tonnes=round(sum(emissions.values()), 6),
            cost_breakdown=costs, emissions_breakdown=emissions, customer_deadline=stamp(voyage.customer_deadline),
            deadline_lateness_hours=max(0, hours(delivery-voyage.customer_deadline)),
            deadline_worst_lateness_hours=max(0, hours(delivery+timedelta(hours=radius)-voyage.customer_deadline)),
            uncertainty_hours=radius, model_version=self.model_version,
            capacity_checked=capacity_checked, execution_profile=dict(option['execution_profile'],
                berth_id=option['berth_id'], start_slot=option['start_slot'], end_slot=option['end_slot'],
                completion_slot=option['completion_slot']))

    def navigation_errors(self, call, voyage):
        if voyage is None:
            return ['MISSING_VOYAGE_AND_CUSTOMER_INPUTS']
        if voyage.position_as_of > self.r.origin:
            return ['POSITION_OBSERVATION_AFTER_PLANNING_ORIGIN']
        if hours(self.r.origin-voyage.position_as_of) > self.policy.maximum_position_age_hours:
            return ['STALE_VESSEL_POSITION']
        earliest_declared_eta = voyage.position_as_of+timedelta(hours=voyage.remaining_distance_nm/voyage.planned_speed_knots)
        if call['id'] not in self.r.arrivals and earliest_declared_eta > parse(call['scheduled_eta'])+timedelta(seconds=1):
            return ['VOYAGE_INPUTS_CONTRADICT_ETA']
        return []

    def find_capacity(self, call, tid, arrival, distance, current, speed, voyage):
        data = copy.deepcopy(self.data)
        clone = next(c for c in data['calls'] if c['id'] == call['id'])
        # Cross-port Resources adds the diversion transit itself; arrival here
        # already includes that leg for the economic and deadline comparison.
        cross_port = self.r.terminals[tid]['port_id'] != self.r.terminals[call['terminal_id']]['port_id']
        clone['scheduled_eta'] = call['scheduled_eta'] if cross_port else stamp(arrival)
        r = Resources(data)
        others = [o for o in self.options if o['call_id'] != call['id']]
        candidates = []
        release = max(r.release(clone)+math.ceil((distance/r.policy.transit_speed_knots)*4) if cross_port else r.release(clone),
                      math.ceil(hours(arrival-r.origin)*4))
        for bid, berth in sorted(r.berths.items()):
            if berth['terminal_id'] != tid:
                continue
            # Include reservation endpoints and the current berth start as well
            # as the bounded hourly search; no free slot is inferred from a
            # congestion probability alone.
            starts = set(range(release, TAIL, self.policy.search_step_minutes//15))
            starts.update(o['end_slot'] for o in others if o['berth_id'] == bid)
            starts.add(self.internal(self.assignments[call['id']])['start_slot'])
            for start in sorted(s for s in starts if release <= s < TAIL):
                if any(o['berth_id'] == bid and o['start_slot'] <= start < o['end_slot'] for o in others):
                    continue
                option = r.profile(clone, bid, start)
                if option is None or conflicts(option, others):
                    continue
                valid, _, _ = yard_trace(r, others+[option], only_terminal=tid)
                if not valid:
                    continue
                if tid != call['terminal_id'] and not yard_trace(r, others+[option], only_terminal=call['terminal_id'])[0]:
                    continue
                outcome = self.outcome(call, option, arrival, speed, distance, voyage)
                deltas, codes = impact(current, outcome, self.policy, 'ALTERNATE_PORT' if cross_port else 'ALTERNATE_TERMINAL')
                candidates.append((outcome, deltas, codes))
                break  # earliest certified slot at this berth
        # The unchanged source ledger was already independently validated.
        # Certify each best witness once rather than rebuilding every yard and
        # tide calendar for every tested start on every receiving berth.
        for candidate in sorted(candidates, key=lambda c: (c[0]['expected_delivery'], c[0]['total_cost_usd'])):
            profile = candidate[0]['execution_profile']
            witness = dict(call_id=call['id'], berth_id=profile['berth_id'], start_slot=profile['start_slot'],
                completion_slot=profile['completion_slot'], end_slot=profile['end_slot'],
                planned_moves=call['load_moves']+call['unload_moves'], waiting_minutes=0,
                crane_ids=sorted({c for s in profile['segments'] for c in s['crane_ids']}), execution_profile=profile)
            try:
                validate_schedule(data, [r.public(o) for o in others+[witness]])
            except DomainError:
                continue
            return candidate
        return None

    def evaluate(self, call_id, candidate_terminal_ids=None):
        if call_id not in self.r.calls:
            raise DomainError('CALL_OUTSIDE_SOURCE_PLAN', 'Vessel call is outside the source planning snapshot', 422)
        call = self.r.calls[call_id]
        home, pid = call['terminal_id'], self.r.terminals[call['terminal_id']]['port_id']
        voyage = self.voyages.get(call_id)
        errors = self.navigation_errors(call, voyage)
        if home not in self.tariffs:
            errors.append('MISSING_CURRENT_TERMINAL_TARIFF')
        assignment = self.assignments.get(call_id)
        if not assignment:
            errors.append('CURRENT_PLAN_HAS_NO_FINITE_SCHEDULE')
        if assignment and not assignment.get('execution_profile'):
            errors.append('MISSING_SOURCE_CAPACITY_CERTIFICATE')
        current = None
        # A current plan can still be compared for an already-arrived vessel if
        # explicit baseline economics exist, but changing its arrival is blocked.
        if not errors:
            arrival = parse(self.r.arrivals.get(call_id, call['scheduled_eta']))
            current = self.outcome(call, self.internal(assignment), arrival, voyage.planned_speed_knots, 0, voyage)
        keep = rejected('KEEP_CURRENT_PLAN', home, *errors)
        if current:
            keep.update(feasible=True, eligible=True, outcome=current, expected_hours_saved=0,
                conservative_hours_saved=0, estimated_cost_change_usd=0,
                estimated_emissions_change_tonnes=0, estimated_net_benefit_usd=0)
        options = [keep]
        move_errors = errors[:]
        if call_id in self.fixed:
            move_errors.append('IMMUTABLE_APPROVED_OR_IN_PROGRESS_RESERVATION')
        if call_id in self.r.arrivals or parse(call['scheduled_eta']) <= self.r.origin:
            move_errors.append('VESSEL_ALREADY_ARRIVED_OR_POSITION_UNCONFIRMED')
        if assignment and self.r.berths[assignment['berth_id']]['terminal_id'] != home:
            move_errors.append('SOURCE_PLAN_ALREADY_DIVERTED_REQUIRES_VOYAGE_REFRESH')
        for action in ('SLOW_STEAM_OR_DELAY_ARRIVAL', 'EARLIER_ARRIVAL'):
            if move_errors:
                options.append(rejected(action, home, *move_errors))
                continue
            distance = self.remaining_distance(voyage)
            if distance <= 0:
                options.append(rejected(action, home, 'NO_REMAINING_VOYAGE'))
                continue
            eta = parse(call['scheduled_eta'])
            if action == 'EARLIER_ARRIVAL':
                speed = voyage.maximum_speed_knots
                arrival = eta-timedelta(hours=distance/voyage.planned_speed_knots-distance/speed)
            else:
                # Hold the baseline reserved berth slot; delay is a sailing
                # adjustment, never an invented delivery-time improvement.
                available = hours(parse(assignment['start'])-eta)+distance/voyage.planned_speed_knots
                speed = max(voyage.minimum_speed_knots, min(voyage.planned_speed_knots, distance/max(available, 1e-6)))
                arrival = eta+timedelta(hours=distance/speed-distance/voyage.planned_speed_knots)
            if abs(speed-voyage.planned_speed_knots) < 1e-6 or arrival < self.r.origin:
                options.append(rejected(action, home, 'NO_PHYSICALLY_POSSIBLE_ARRIVAL_ADJUSTMENT'))
                continue
            if action == 'SLOW_STEAM_OR_DELAY_ARRIVAL':
                # Retain the entire source reservation/crane profile. Slowing
                # the voyage changes its release and fuel, not berth ownership.
                shifted = copy.deepcopy(self.data)
                next(c for c in shifted['calls'] if c['id'] == call_id)['scheduled_eta'] = stamp(arrival)
                rr = Resources(shifted)
                try:
                    validate_schedule(shifted, [rr.public(o) for o in self.options])
                except DomainError:
                    candidate = None
                else:
                    candidate = (self.outcome(call, self.internal(assignment), arrival, speed, 0, voyage), {}, [])
            else:
                candidate = self.find_capacity(call, home, arrival, 0, current, speed, voyage)
            if candidate is None:
                options.append(rejected(action, home, 'NO_COMPATIBLE_RECEIVING_CAPACITY'))
                continue
            outcome, _, _ = candidate
            if action == 'SLOW_STEAM_OR_DELAY_ARRIVAL' and parse(outcome['berth_start']) != parse(assignment['start']):
                # A slower vessel must retain a certified slot rather than
                # losing its reservation and relying on a new congested queue.
                options.append(rejected(action, home, 'SLOW_STEAM_CANNOT_RETAIN_RESERVED_SLOT'))
                continue
            deltas, codes = impact(current, outcome, self.policy, action)
            options.append(dict(action=action, terminal_id=home, feasible=True, eligible=not codes,
                rejection_codes=codes, evidence={'reservation_ledger_checked': True}, outcome=outcome, **deltas))
        targets = candidate_terminal_ids if candidate_terminal_ids is not None else sorted(self.r.terminals)
        for tid in targets:
            if tid not in self.r.terminals:
                raise DomainError('TERMINAL_OUTSIDE_SOURCE_PLAN', 'Candidate terminal has no receiving snapshot in the source run')
            if tid == home:
                continue
            action = 'ALTERNATE_TERMINAL' if self.r.terminals[tid]['port_id'] == pid else 'ALTERNATE_PORT'
            bid = next((b['id'] for b in self.r.berths.values() if b['terminal_id'] == tid), None)
            distance = self.policy.terminal_transfer_nm if action == 'ALTERNATE_TERMINAL' else self.r.distance(call, bid) if bid else None
            codes = move_errors[:]
            if distance is None:
                codes.append('MISSING_NAVIGATION_DISTANCE')
            elif action == 'ALTERNATE_PORT' and distance > self.policy.maximum_diversion_nm:
                codes.append('DIVERSION_DISTANCE_EXCEEDS_NEARBY_PORT_LIMIT')
            tariff = self.tariffs.get(tid)
            if tariff is None:
                codes.append('MISSING_RECEIVING_TARIFF_AND_INLAND_ROUTE')
            elif not tariff.cargo_booking_confirmed:
                codes.append('RECEIVING_CARGO_BOOKING_UNCONFIRMED')
            if codes:
                options.append(rejected(action, tid, *codes, diversion_distance_nm=distance,
                    maximum_diversion_nm=self.policy.maximum_diversion_nm))
                continue
            speed = voyage.planned_speed_knots
            transit_speed = self.r.policy.transit_speed_knots if action == 'ALTERNATE_PORT' else speed
            arrival = parse(call['scheduled_eta'])+timedelta(hours=distance/transit_speed)
            candidate = self.find_capacity(call, tid, arrival, distance, current, speed, voyage)
            if candidate is None:
                options.append(rejected(action, tid, 'NO_COMPATIBLE_RECEIVING_CAPACITY',
                    diversion_distance_nm=distance, checked_constraints=['dimensions', 'cargo', 'equipment',
                    'tide', 'weather', 'crane_calendars', 'berth_reservations', 'yard_capacity']))
                continue
            outcome, deltas, codes = candidate
            options.append(dict(action=action, terminal_id=tid, feasible=True, eligible=not codes,
                rejection_codes=codes, evidence={'reservation_ledger_checked': True,
                    'receiving_capacity_reserved': False, 'diversion_distance_nm': distance}, outcome=outcome, **deltas))
        # Always expose all five decision classes, even without receiving ports.
        for action in ('ALTERNATE_TERMINAL', 'ALTERNATE_PORT'):
            if not any(o['action'] == action for o in options):
                options.append(rejected(action, None, 'NO_RECEIVING_TERMINAL_IN_SOURCE_SNAPSHOT'))
        alternatives = [o for o in options[1:] if o['eligible']]
        winner = max(alternatives, key=lambda o: (o['estimated_net_benefit_usd'], o['expected_hours_saved'], o['terminal_id'])) if alternatives else keep
        expiry = self.r.origin+timedelta(minutes=self.policy.expiry_minutes)
        if voyage:
            expiry = min(expiry, voyage.position_as_of+timedelta(hours=self.policy.maximum_position_age_hours))
        reasons = [dict(code='QUANTIFIED_END_TO_END_COMPARISON', message='Delivery time includes sailing, certified handling and the supplied inland route.',
            current_wait_hours=current['planned_wait_hours'] if current else None,
            raw_model_wait_hours=current['raw_model_wait_hours'] if current else None,
            recommended_wait_hours=winner['outcome']['planned_wait_hours'] if winner['outcome'] else None,
            expected_hours_saved=winner['expected_hours_saved'], estimated_cost_change_usd=winner['estimated_cost_change_usd']),
            dict(code='PHYSICAL_CAPACITY_AND_COMPATIBILITY', message='Changes require a compatible receiving slot without displacing existing reservations.',
                 capacity_checked=bool(winner['outcome'] and winner['outcome']['capacity_checked']),
                 current_berth_id=current['berth_id'] if current else None,
                 recommended_berth_id=winner['outcome']['berth_id'] if winner['outcome'] else None,
                 receiving_berth_start=winner['outcome']['berth_start'] if winner['outcome'] else None),
            dict(code='BENEFIT_AND_UNCERTAINTY_GATE', message='Select only benefits above policy thresholds; otherwise retain the current plan.',
                selected_net_benefit_usd=winner['estimated_net_benefit_usd'], minimum_net_benefit_usd=self.policy.minimum_net_benefit_usd,
                conservative_hours_saved=winner['conservative_hours_saved'],
                estimated_co2_change_tonnes=winner['estimated_emissions_change_tonnes'],
                deadline_worst_lateness_hours=winner['outcome']['deadline_worst_lateness_hours'] if winner['outcome'] else None,
                rejection_codes=sorted({c for o in options[1:] for c in o['rejection_codes']}))]
        risks = ['Independent what-if: receiving capacity is checked but not reserved; multiple proposals require a joint CP-SAT replan.',
            'Operator must confirm voyage position, cargo booking, tariffs, inland customer route and deadline, then approve the refreshed supervisor plan.',
            'Fuel, CO2 and value-of-time are configurable engineering proxies, not measured voyage emissions or commercial quotations.',
            'Waiting time is conditional on the executable plan. The original trained prediction is retained separately as risk evidence.',
            'Delivery bands are conservative scenario envelopes, not calibrated statistical confidence intervals.',
            'Cross-port distance is great-circle port-to-port via the original port; navigation exclusions and actual shipping lanes require operator verification.',
            'Known weather, tide fit and outage assumptions are inherited from the source plan; unknown future disruptions require rolling replanning.',
            'Every option holds other vessels fixed; this bounded search can reject opportunities a joint optimiser might find.']
        risks.append('A position up to the configured age is propagated to planning origin at declared speed; actual navigable distance and fuel curves require confirmation.')
        if voyage:
            risks.append('Voyage/customer input source: '+voyage.source_label)
        if home in self.tariffs:
            risks.append('Baseline tariff/inland input source: '+self.tariffs[home].source_label)
        if winner['terminal_id'] in self.tariffs and winner['terminal_id'] != home:
            risks.append('Receiving tariff/inland input source: '+self.tariffs[winner['terminal_id']].source_label)
        return dict(call_id=call_id, port_id=pid, recommended_action=winner['action'], current_plan_outcome=current,
            recommended_plan_outcome=winner['outcome'], expected_hours_saved=winner['expected_hours_saved'],
            estimated_cost_change_usd=winner['estimated_cost_change_usd'],
            estimated_emissions_change_tonnes=winner['estimated_emissions_change_tonnes'], confidence_level='LOW',
            main_reasons=reasons, risks_and_assumptions=risks, expires_at=stamp(expiry), operator_approval_required=True,
            independent_what_if=True, is_expired=False, operationally_actionable=False, options=options)
