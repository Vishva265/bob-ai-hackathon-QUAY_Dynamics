"""Bounded executable candidate CP-SAT, FCFS baseline and validated fallback.

OPTIMAL means optimal within the documented candidate grid, not all continuous
start times/crane patterns. Greedy witnesses are included and supplied as hints.
"""
import math
import time
from collections import defaultdict
from ortools.sat.python import cp_model

from app.errors import DomainError
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, SLOTS, TAIL, SHIFT, TEU_SCALE, yard_trace
from app.optimisation.metrics import call_terms, report
from app.synthetic.simulator import parse, stamp

SCALE = 400000
OFFSETS = (0, 1, 2, 4, 6, 8, 12, 16, 24, 32, 40, 48, 60, 72, 84, 96)


def conflicts(option, chosen):
    for old in chosen:
        # Cranes are installed at exactly one berth; transfers are outside this
        # model. Different compatible berths cannot share an individual crane.
        if old['berth_id'] != option['berth_id']:
            continue
        if old['berth_id'] == option['berth_id'] and option['start_slot'] < old['end_slot'] and old['start_slot'] < option['end_slot']:
            return True
        for a in option['execution_profile']['segments']:
            for b in old['execution_profile']['segments']:
                if a['start_slot'] < b['end_slot'] and b['start_slot'] < a['end_slot'] and set(a['crane_ids']) & set(b['crane_ids']):
                    return True
    return False


def fixed_options(r):
    fixed, pending, failures = [], [], []
    committed = {a['call_id'] for a in r.data['commitments']}
    for a in r.data['commitments']:
        if parse(a['start']) < r.origin:
            failures.append(dict(call_id=a['call_id'], code='FROZEN_PROGRESS_CONFIRMATION',
                message='An approved operation began before this new planning origin; confirm actual handling progress and departure before advancing its frozen reservation'))
        start = max(0, math.floor((parse(a['start'])-r.origin).total_seconds()/900))
        end = min(TAIL, math.ceil((parse(a['end'])-r.origin).total_seconds()/900))
        if end <= start:
            continue
        profile = a.get('execution_profile')
        if profile:
            import copy
            profile = copy.deepcopy(profile)
            offset = round((parse(profile.get('origin', r.data['as_of']))-r.origin).total_seconds()/900)
            profile['segments'] = [dict(seg, start_slot=max(0, seg['start_slot']+offset), end_slot=min(TAIL, seg['end_slot']+offset))
                for seg in profile['segments'] if seg['end_slot']+offset > 0 and seg['start_slot']+offset < TAIL]
            profile['productive_slots'] = [i+offset for i in profile['productive_slots'] if 0 <= i+offset < TAIL]
            profile['shift_cranes'] = [max((len(seg['crane_ids']) for seg in profile['segments'] if seg['start_slot'] < (i+1)*SHIFT and seg['end_slot'] > i*SHIFT), default=0) for i in range(15)]
            profile.update(commitment=True, origin=stamp(r.origin))
        else:
            profile = dict(segments=[dict(start_slot=start, end_slot=end, crane_ids=a['crane_ids'], shift_index=start//SHIFT, moves=a['planned_moves'])],
                productive_slots=list(range(start, end)), shift_cranes=[len(a['crane_ids']) if start < (i+1)*SHIFT and end > i*SHIFT else 0 for i in range(15)],
                strategy='legacy_approved_reservation', reroute_distance_nm=0, release_slot=start, carry=False, commitment=True)
        fixed.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], start_slot=start, end_slot=end,
            completion_slot=min(end, math.ceil((parse(a.get('completion_time') or a['end'])-r.origin).total_seconds()/900)),
            waiting_minutes=a['waiting_minutes'], planned_moves=a['planned_moves'], crane_ids=a['crane_ids'], execution_profile=profile))
    for carry in r.data['carry_in']:
        if carry['call_id'] in committed:
            continue
        if carry['remaining_moves'] <= 1e-6:
            pending.append(carry['call_id'])
            # Keep the berth reserved until an actual departure is observed.
            fixed.append(dict(call_id=carry['call_id'], berth_id=carry['berth_id'], start_slot=0, end_slot=TAIL,
                completion_slot=0, waiting_minutes=0, planned_moves=0, crane_ids=[], execution_profile=dict(
                    segments=[], productive_slots=[], shift_cranes=[0]*15, strategy='await_departure', reroute_distance_nm=0,
                    release_slot=0, carry=True, commitment=True)))
            continue
        call = r.calls[carry['call_id']]
        option = r.profile(call, carry['berth_id'], 0, carry=carry)
        if option is None:
            failures.append(dict(call_id=carry['call_id'], code='CARRY_IN_NO_COMPLETION',
                message='Observed in-progress work cannot safely finish within 120 hours under known weather, tides and equipment calendars'))
        else:
            fixed.append(option)
    for option in fixed:
        for seg in option['execution_profile']['segments']:
            pid = r.terminals[r.berths[option['berth_id']]['terminal_id']]['port_id']
            if any(r.closed[pid][i] or r.berth_closed[option['berth_id']][i] for i in range(seg['start_slot'], seg['end_slot'])) or any(
                cid not in r.available or not all(r.available[cid][i] for i in range(seg['start_slot'], seg['end_slot']))
                for cid in seg['crane_ids']):
                failures.append(dict(call_id=option['call_id'], code='FIXED_CALENDAR_CONFLICT',
                    message='Frozen approved processing intersects a known crane outage or weather closure; release eligible work or repair the operational commitment'))
    return fixed, pending, failures


def candidate_berths(r, call):
    original = [bid for bid, b in r.berths.items() if b['terminal_id'] == call['terminal_id']]
    if not r.policy.allow_rerouting:
        return sorted(original)
    # A route that passed the recommendation gates and was explicitly approved
    # can be fixed as the destination for the joint replan.  This prevents a
    # solver objective from silently dispatching an unreviewed diversion.
    approvals = r.data.get('approved_routing_terminal_ids', {})
    approved = approvals.get(call['id'])
    if approved:
        return sorted(bid for bid, b in r.berths.items() if b['terminal_id'] == approved)
    if approvals:
        return sorted(original)
    original_pid = r.terminals[call['terminal_id']]['port_id']
    alternate = [bid for bid, b in r.berths.items() if r.terminals[b['terminal_id']]['port_id'] != original_pid and r.distance(call, bid) is not None]
    return sorted(original) + sorted(alternate, key=lambda bid: (r.distance(call, bid), bid))[:4]


def catalogue(r, calls, fixed):
    result = {}
    for call in calls:
        options = []
        bids = candidate_berths(r, call)
        extra = {o['end_slot'] for o in fixed if o['berth_id'] in bids}
        starts = sorted({r.release(call)+h*4 for h in OFFSETS} | extra)
        for start in starts:
            for bid in bids:
                for strategy in ('maximum', 'economical', 'shift_balanced'):
                    if len(options) >= r.policy.max_candidates_per_call:
                        break
                    option = r.profile(call, bid, start, strategy)
                    if option and not conflicts(option, fixed):
                        signature = (bid, start, option['end_slot'], tuple((s['start_slot'], s['end_slot'], tuple(s['crane_ids'])) for s in option['execution_profile']['segments']))
                        if not any(o['_signature'] == signature for o in options):
                            option['_signature'] = signature
                            options.append(option)
        result[call['id']] = options
        # An unchanged approved executable option must remain selectable even
        # when its exact start/pattern is outside the bounded demo catalogue.
        previous = next((a for a in r.data.get('previous_assignments', []) if a['call_id'] == call['id']), None)
        if previous and parse(previous['start']) >= r.origin and previous.get('execution_profile'):
            saved = dict(r.data, commitments=[previous], carry_in=[])
            prior, _, errors = fixed_options(Resources(saved))
            if prior and not errors:
                option = prior[0]
                option['execution_profile'].pop('commitment', None)
                release = r.release(call)+math.ceil((r.distance(call,option['berth_id']) or 0)/r.policy.transit_speed_knots*4)
                option['waiting_minutes'] = max(0, option['start_slot']-release)*15
                option['execution_profile'].update(release_slot=release,
                    additional_wait_minutes=option['waiting_minutes'], accrued_wait_minutes=r.accrued_wait_minutes(call))
                from app.optimisation.validation import validate_schedule
                try:
                    validate_schedule(r.data, [r.public(option)])
                except DomainError:
                    pass  # changed observations invalidate this previous witness
                else:
                    if not conflicts(option, fixed):
                        options.append(option)
    return result


def greedy(r, calls, fixed, priority=False):
    selected, deferred = list(fixed), []
    ordered = sorted(calls, key=lambda c: (r.release(c), c['priority'] if priority else c['id'], c['id']))
    for call in ordered:
        found = None
        bids = candidate_berths(r, call)
        starts = sorted(set(range(r.release(call), TAIL, 4)) | {o['end_slot'] for o in selected if o['berth_id'] in bids})
        for start in starts:
            options = [o for bid in bids if (o := r.profile(call, bid, start, 'maximum' if priority else 'fcfs')) and not conflicts(o, selected)]
            for option in sorted(options, key=lambda o: (o['end_slot'], o['berth_id'])):
                tid = r.berths[option['berth_id']]['terminal_id']
                if yard_trace(r, selected+[option], only_terminal=tid)[0]:
                    found = option
                    break
            if found:
                break
        if found:
            selected.append(found)
        else:
            deferred.append(call['id'])
    return selected, deferred


def solve(r, calls, fixed, choices, witness, time_limit):
    model = cp_model.CpModel()
    witness_ids = {o['call_id']: o for o in witness}
    witness_valid, witness_trace, witness_gates = yard_trace(r, witness)
    expected_trace = {(row['terminal_id'], round((parse(row['timestamp'])-r.origin).total_seconds()/900)): row for row in witness_trace}
    berth_intervals, crane_intervals = defaultdict(list), defaultdict(list)
    for o in fixed:
        berth_intervals[o['berth_id']].append(model.new_fixed_size_interval_var(o['start_slot'], o['end_slot']-o['start_slot'], 'fixed-'+o['call_id']))
        for seg in o['execution_profile']['segments']:
            for cid in seg['crane_ids']:
                crane_intervals[cid].append(model.new_fixed_size_interval_var(seg['start_slot'], seg['end_slot']-seg['start_slot'], 'fixed-crane-'+cid+'-'+o['call_id']+'-'+str(seg['start_slot'])))
    objectives, variables, deferrals, assumption_names = [], {}, {}, {}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    crane_days = defaultdict(list)
    for call in calls:
        cid = call['id']
        deferred = model.new_bool_var(cid+'-deferred')
        accepted = model.new_bool_var(cid+'-accepted')
        rerouted = model.new_bool_var(cid+'-rerouted')
        deferrals[cid] = deferred
        presences = []
        for index, o in enumerate(choices[cid]):
            present = model.new_bool_var(f'{cid}-option-{index}')
            variables[(cid, index)] = present
            presences.append(present)
            berth_intervals[o['berth_id']].append(model.new_optional_fixed_size_interval_var(o['start_slot'], o['end_slot']-o['start_slot'], present, f'{cid}-berth-{index}'))
            for seg in o['execution_profile']['segments']:
                for crane_id in seg['crane_ids']:
                    crane_intervals[crane_id].append(model.new_optional_fixed_size_interval_var(seg['start_slot'], seg['end_slot']-seg['start_slot'], present, f'{cid}-crane-{index}-{crane_id}-{seg["start_slot"]}'))
                    for day in range(5):
                        minutes = max(0, min(seg['end_slot'], (day+1)*96)-max(seg['start_slot'], day*96))*15
                        if minutes:
                            crane_days[(crane_id, day)].append(minutes*present)
            tid = r.berths[o['berth_id']]['terminal_id']
            incoming[(tid, o['start_slot'])].append(math.ceil(call['unload_moves']*call['teu_per_move']*TEU_SCALE)*present)
            outgoing[(tid, o['completion_slot'])].append(math.floor(call['load_moves']*call['teu_per_move']*TEU_SCALE)*present)
            terms = call_terms(r, o)
            occupied = max(0, min(SLOTS, o['end_slot'])-o['start_slot'])/4
            coefficient = sum(getattr(r.policy.weights, key)*v for key, v in terms.items())-occupied*r.policy.weights.unused_berth_capacity
            objectives.append(round(coefficient*SCALE)*present)
        model.add(sum(presences) == accepted)
        model.add(accepted+deferred == 1)
        model.add(rerouted == sum(variables[(cid, i)] for i, o in enumerate(choices[cid]) if o['execution_profile']['reroute_distance_nm'] > 0))
        start_var = model.new_int_var(0, TAIL, cid+'-berthing-start')
        complete_var = model.new_int_var(0, TAIL, cid+'-service-completion')
        model.add(start_var == sum(o['start_slot']*variables[(cid, i)] for i, o in enumerate(choices[cid]))+SLOTS*deferred)
        model.add(complete_var == sum(o['completion_slot']*variables[(cid, i)] for i, o in enumerate(choices[cid]))+SLOTS*deferred)
        hint = witness_ids.get(cid)
        model.add_hint(accepted, int(hint is not None))
        model.add_hint(rerouted, int(hint is not None and hint['execution_profile']['reroute_distance_nm'] > 0))
        model.add_hint(start_var, hint['start_slot'] if hint else SLOTS)
        model.add_hint(complete_var, hint['completion_slot'] if hint else SLOTS)
        for shift in range(15):
            q = model.new_int_var(0, r.vessels[call['vessel_id']]['max_cranes'], f'{cid}-shift-{shift}-crane-count')
            model.add(q == sum(o['execution_profile']['shift_cranes'][shift]*variables[(cid, i)] for i, o in enumerate(choices[cid])))
            model.add_hint(q, hint['execution_profile']['shift_cranes'][shift] if hint else 0)
        if not r.policy.allow_deferral:
            required = model.new_bool_var(cid+'-required')
            model.add(accepted == 1).only_enforce_if(required)
            model.add_assumption(required)
            assumption_names[required.index] = cid
        objectives.append(round(sum(getattr(r.policy.weights, k)*v for k, v in call_terms(r, call=call).items())*SCALE)*deferred)
    for intervals in list(berth_intervals.values())+list(crane_intervals.values()):
        model.add_no_overlap(intervals)
    fixed_in, fixed_out = defaultdict(int), defaultdict(int)
    for o in fixed:
        from app.optimisation.resources import staging_moves
        unload, load = staging_moves(r, o)
        tid = r.berths[o['berth_id']]['terminal_id']
        fixed_in[(tid, o['start_slot'])] += math.ceil(unload*TEU_SCALE)
        fixed_out[(tid, o['completion_slot'])] += math.floor(load*TEU_SCALE)
    gate_vars = {}
    for tid, terminal in r.terminals.items():
        capacity = math.floor(r.planning_capacity[tid]*TEU_SCALE)
        stock = math.ceil(r.yards[tid]['closing_teu']*TEU_SCALE)
        gate_vars[tid] = []
        for i in range(TAIL+1):
            peak = model.new_int_var(0, capacity, f'{tid}-{i}-yard-peak')
            after = model.new_int_var(0, capacity, f'{tid}-{i}-yard-after-load')
            model.add(peak == stock+sum(incoming[(tid, i)])+fixed_in[(tid, i)])
            model.add(after == peak-sum(outgoing[(tid, i)])-fixed_out[(tid, i)])
            row = expected_trace[(tid, i)]
            if witness_valid:
                model.add_hint(peak, round(row['peak_teu']*TEU_SCALE))
                model.add_hint(after, round(row['closing_teu']*TEU_SCALE)+(witness_gates[tid][i] if i<TAIL else 0))
            excess = model.new_int_var(0, capacity, f'{tid}-{i}-yard-congestion')
            model.add_max_equality(excess, [0, peak-math.floor(terminal['yard_capacity_teu']*r.policy.yard_congestion_fraction*TEU_SCALE)])
            if witness_valid:
                model.add_hint(excess, max(0, round(row['peak_teu']*TEU_SCALE)-math.floor(terminal['yard_capacity_teu']*r.policy.yard_congestion_fraction*TEU_SCALE)))
            if i < TAIL:
                objectives.append(round(r.policy.weights.yard_congestion*SCALE*.25/(1000*TEU_SCALE))*excess)
            if i < TAIL:
                factor = min([e['value'] for e in r.data['disruptions'] if e['kind'] == 'yard_congestion' and e.get('terminal_id') == tid
                    and parse(e['start']) <= r.times[i] < parse(e['end'])] or [1])
                gate = model.new_int_var(0, math.floor(terminal['gate_capacity_teu_per_hour']*.25*factor*TEU_SCALE), f'{tid}-{i}-gate')
                stock = model.new_int_var(0, capacity, f'{tid}-{i}-yard-close')
                model.add(stock == after-gate)
                if witness_valid:
                    model.add_hint(stock, round(row['closing_teu']*TEU_SCALE))
                gate_vars[tid].append(gate)
    for o in fixed:
        for seg in o['execution_profile']['segments']:
            for cid in seg['crane_ids']:
                for day in range(5):
                    crane_days[(cid, day)]
    for (crane_id, day), expressions in crane_days.items():
        fixed_minutes = sum(max(0, min(s['end_slot'], (day+1)*96)-max(s['start_slot'], day*96))*15
            for o in fixed for s in o['execution_profile']['segments'] if crane_id in s['crane_ids'])
        overtime = model.new_int_var(0, 1440, f'{crane_id}-{day}-overtime')
        model.add_max_equality(overtime, [0, sum(expressions)+fixed_minutes-round(r.policy.regular_crane_hours_per_day*60)])
        if witness_valid:
            minutes = sum(max(0, min(seg['end_slot'], (day+1)*96)-max(seg['start_slot'], day*96))*15
                          for o in witness for seg in o['execution_profile']['segments'] if crane_id in seg['crane_ids'])
            model.add_hint(overtime, max(0, minutes-round(r.policy.regular_crane_hours_per_day*60)))
        objectives.append(round(r.policy.weights.crane_overtime*SCALE/60)*overtime)
    constant = len(r.berths)*72*r.policy.weights.unused_berth_capacity
    for o in fixed:
        constant += sum(getattr(r.policy.weights, k)*v for k, v in call_terms(r, o).items())
        constant -= max(0, min(SLOTS, o['end_slot'])-o['start_slot'])/4*r.policy.weights.unused_berth_capacity
    model.minimize(sum(objectives)+round(constant*SCALE))
    for call in calls:
        cid = call['id']
        selected = witness_ids.get(cid)
        for i, o in enumerate(choices[cid]):
            model.add_hint(variables[(cid, i)], int(o is selected))
        model.add_hint(deferrals[cid], int(selected is None))
    if witness_valid:
        for tid, gates in gate_vars.items():
            for i, v in enumerate(gates):
                model.add_hint(v, witness_gates[tid][i])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 42
    solver.parameters.cp_model_presolve = False
    solver.parameters.search_branching = cp_model.HINT_SEARCH
    status = solver.solve(model)
    info = dict(solver_status=solver.status_name(status), solver_runtime_ms=round(solver.wall_time*1000),
        decision_variables=dict(candidate_selection=len(variables), accepted=len(calls), start=len(calls), completion=len(calls),
                               shift_crane_counts=len(calls)*15, deferrals=len(calls), rerouted=len(calls)),
        candidate_count=len(variables), candidate_grid_wait_hours=list(OFFSETS), objective_scale=SCALE)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        info['infeasibility_core_call_ids'] = [assumption_names.get(abs(i), str(i)) for i in solver.sufficient_assumptions_for_infeasibility()] if status == cp_model.INFEASIBLE else []
        return None, None, None, info
    selected = list(fixed)+[o for cid, options in choices.items() for i, o in enumerate(options) if solver.value(variables[(cid, i)])]
    deferred_ids = [cid for cid, v in deferrals.items() if solver.value(v)]
    gates = {tid: [solver.value(v) for v in values] for tid, values in gate_vars.items()}
    info.update(objective=solver.objective_value/SCALE, best_bound=solver.best_objective_bound/SCALE)
    return selected, deferred_ids, gates, info


def schedule(data, time_limit=5):
    began = time.perf_counter()
    data = prepare(data)
    r = Resources(data)
    committed = {a['call_id'] for a in data['commitments']}
    carried = {c['call_id'] for c in data['carry_in']}
    departed = {e['call_id'] for e in data.get('known_call_observations', []) if e['kind'] == 'departure'}
    calls = [c for c in r.calls.values() if c['id'] not in committed|carried|departed and r.release(c) < SLOTS]
    if len(calls) > 250:
        raise DomainError('INSTANCE_TOO_LARGE', 'The live-demo engine supports at most 250 pending vessels')
    fixed, pending, failures = fixed_options(r)
    baseline, baseline_deferred = greedy(r, calls, fixed)
    witness, witness_deferred = greedy(r, calls, fixed, priority=True)
    choices = catalogue(r, calls, fixed)
    for options in [baseline, witness]:
        for o in options:
            if o['call_id'] in choices and not any(x is o for x in choices[o['call_id']]):
                choices[o['call_id']].append(o)
    if failures or not yard_trace(r, fixed)[0] or any(conflicts(o, fixed[:i]) for i, o in enumerate(fixed)):
        selected, deferred, gates = None, None, None
        info = dict(solver_status='INFEASIBLE', solver_runtime_ms=0, infeasibility_core_call_ids=[])
        failures.append(dict(code='FIXED_STATE_CONFLICT', message='Fixed operations exceed safe yard capacity or overlap; an operator must repair the existing state'))
    else:
        selected, deferred, gates, info = solve(r, calls, fixed, choices, witness, min(10, max(.1, time_limit)))
    source = 'cp_sat'
    if selected is None:
        if not failures and yard_trace(r, witness)[0] and (r.policy.allow_deferral or not witness_deferred):
            selected, deferred, gates = witness, witness_deferred, yard_trace(r, witness)[2]
            source = 'greedy_fallback'
        else:
            selected, deferred, gates = [], [c['id'] for c in calls], None
            source = 'no_feasible_schedule'
    if source != 'no_feasible_schedule':
        from app.optimisation.validation import validate_schedule
        try:
            validate_schedule(data, [r.public(o) for o in selected if o['planned_moves'] > 0], deferred, gates)
        except DomainError as error:
            failures.append(dict(code=error.code, message=error.message))
            try:
                if not r.policy.allow_deferral and witness_deferred:
                    raise DomainError('REQUIRED_ACCEPTANCE', 'Fallback cannot cover all required vessels')
                fallback_gates = yard_trace(r, witness)[2]
                validate_schedule(data, [r.public(o) for o in witness if o['planned_moves'] > 0], witness_deferred, fallback_gates)
                selected, deferred, gates = witness, witness_deferred, fallback_gates
                source = 'greedy_fallback'
            except DomainError as fallback_error:
                failures.append(dict(code=fallback_error.code, message=fallback_error.message))
                selected, deferred, gates = [], [c['id'] for c in calls], None
                source = 'no_feasible_schedule'
    base_metrics, base_objective, base_trace, _ = report(r, baseline, baseline_deferred)
    metrics, objective, trace, gates = report(r, selected, deferred, gates)
    # Resource checks on an empty failed schedule cannot certify required work.
    # Fixed operations or mandatory acceptance may already be impossible.
    if source == 'no_feasible_schedule':
        metrics['validation_passed'] = False
    explanations = list(failures)
    if info.get('infeasibility_core_call_ids'):
        explanations.append(dict(code='JOINT_ACCEPTANCE_INFEASIBLE',
            message='These required vessels cannot all fit the shared berth/crane calendars, tide windows and safe conserved yard capacity within 120 hours',
            call_ids=info['infeasibility_core_call_ids']))
    for cid in deferred:
        explanations.append(dict(call_id=cid, code='NO_FEASIBLE_ACCEPTANCE' if not choices[cid] else 'RESOURCE_OR_YARD_CONFLICT',
            message='No compatible tide/equipment/calendar option fits the bounded horizon' if not choices[cid]
            else 'Shared berth/crane capacity or conserved yard staging requires this vessel to be deferred',
            evidence=dict(candidate_count=len(choices[cid]), terminal_id=r.calls[cid]['terminal_id'],
                          compatible_berths=sorted({o['berth_id'] for o in choices[cid]}), horizon_hours=120)))
    comparison = dict(baseline=base_metrics, optimised=metrics, baseline_objective=base_objective,
        estimated_cost_savings_usd=base_metrics['estimated_cost_usd']-metrics['estimated_cost_usd'],
        estimated_emissions_savings_tonnes_co2=base_metrics['estimated_emissions_tonnes_co2']-metrics['estimated_emissions_tonnes_co2'],
        same_served_vessels=set(o['call_id'] for o in baseline)==set(o['call_id'] for o in selected),
        baseline_assignments=[r.public(o) for o in baseline if o['planned_moves'] > 0])
    diagnostics = dict(info, method='cp_sat_executable_candidate_v2', schedule_source=source,
        fallback_status='FEASIBLE' if source == 'greedy_fallback' else None, slot_minutes=15, completion_tail_hours=48,
        candidate_calls=len(calls), input_port_ids=data['port_ids'], unscheduled_call_ids=sorted(deferred),
        pending_departure_call_ids=pending, objective_breakdown=objective, metrics=metrics, comparison=comparison,
        baseline_yard_balance=base_trace[::4], yard_balance=trace[::4], gate_plan=gates, infeasibility_explanations=explanations,
        policy=r.policy.model_dump(), tide_quality=r.tide_quality, released_commitment_ids=data['released_commitment_ids'],
        yard_planning_capacity_teu=r.planning_capacity,
        assumptions=['OPTIMAL is relative to the bounded candidate start/crane-pattern catalogue. FCFS and priority-greedy witnesses are included.',
            'Service rates use the safe-yard ceiling, persisted weather and known calendars. Tide is fitted from past observations with a conservative residual margin.',
            'Full discharge stages at entry and full loading occurs at completion; yard stock and optional gate-out are hard constraints on the 15-minute grid.',
            'Cost/emissions are configurable planning proxies, not invoices or measured emissions. Deferrals carry full-demand cost penalties; served-only waits exclude deferrals.',
            'Previously approved work is fixed unless explicit replanning releases starts beyond the configured freeze window.'])
    assignments = [r.public(o) for o in selected if o['planned_moves'] > 0 and not o['execution_profile'].get('commitment')]
    recommendations = []
    for o in selected:
        if o['execution_profile']['reroute_distance_nm']:
            recommendations.append(dict(call_id=o['call_id'], kind='alternate_port',
                alternate_port_id=r.terminals[r.berths[o['berth_id']]['terminal_id']]['port_id'], adjusted_eta=stamp(r.times[o['execution_profile']['release_slot']]),
                reasons=[dict(code='JOINT_ROUTING_ALLOCATION', message='Destination resources, cargo compatibility and distance/speed transit are included in the schedule',
                    evidence=dict(distance_nm=o['execution_profile']['reroute_distance_nm'], speed_knots=r.policy.transit_speed_knots))]))
        elif o['waiting_minutes'] >= 240 and o['call_id'] not in r.arrivals and not o['execution_profile'].get('carry') and not o['execution_profile'].get('commitment'):
            recommendations.append(dict(call_id=o['call_id'], kind='delayed_arrival', alternate_port_id=None, adjusted_eta=stamp(r.times[o['start_slot']]),
                reasons=[dict(code='ARRIVAL_ADJUSTMENT', message='Arrive at the allocated berth time to reduce anchorage waiting; this does not claim a shorter total completion time', evidence=dict(avoided_anchorage_minutes=o['waiting_minutes']))]))
    for cid in deferred:
        recommendations.append(dict(call_id=cid, kind='deferral', alternate_port_id=None, adjusted_eta=stamp(r.times[SLOTS]),
            reasons=[dict(code='DEFERRED_OUTSIDE_PLAN', message='Explicitly unaccepted within this plan; receiving a new ETA requires operator confirmation', evidence=dict(planning_horizon_hours=72))]))
    diagnostics['total_runtime_ms'] = round((time.perf_counter()-began)*1000)
    return assignments, recommendations, info['solver_status'], diagnostics, diagnostics['total_runtime_ms']
