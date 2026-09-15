"""Build a nine-shift publication from measured inputs and executable schedules."""
from collections import defaultdict
from datetime import timedelta

from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, yard_trace
from app.optimisation.engine import fixed_options
from app.synthetic.simulator import parse, stamp

MATERIAL_MINUTES = 30


def internal(a, r):
    return dict(call_id=a['call_id'], berth_id=a['berth_id'],
        start_slot=round((parse(a['start'])-r.origin).total_seconds()/900),
        completion_slot=round((parse(a['completion_time'])-r.origin).total_seconds()/900),
        end_slot=round((parse(a['end'])-r.origin).total_seconds()/900), waiting_minutes=a['waiting_minutes'],
        planned_moves=a['planned_moves'], crane_ids=a['crane_ids'], execution_profile=a['execution_profile'])


def material_changes(old, new, triggers, carry, completed_ids=()):
    before, after = {a['call_id']: a for a in old}, {a['call_id']: a for a in new}
    result = []
    for cid in sorted(set(before) | set(after)):
        a, b = before.get(cid), after.get(cid)
        if cid in completed_ids:
            continue
        fields = []
        if a is None:
            fields.append('NEW_CALL')
        elif b is None:
            fields.append('NO_REPLACEMENT_ASSIGNMENT')
        else:
            if a['berth_id'] != b['berth_id']:
                fields.append('BERTH_CHANGED')
            if set(a['crane_ids']) != set(b['crane_ids']):
                fields.append('CRANE_BUNDLE_CHANGED')
            for name in ('start', 'completion_time', 'end'):
                first = carry[cid]['started_at'] if name == 'start' and cid in carry else a[name]
                second = carry[cid]['started_at'] if name == 'start' and cid in carry else b[name]
                if abs((parse(first)-parse(second)).total_seconds()) >= MATERIAL_MINUTES*60:
                    fields.append(name.upper()+'_CHANGED')
            if a.get('execution_profile', {}).get('shift_cranes') != b.get('execution_profile', {}).get('shift_cranes'):
                # Shift arrays use different origins on a rolling plan. Compare
                # absolute crane segments, not their shifted array indices.
                def segments(x):
                    p = x.get('execution_profile') or {}
                    origin = parse(p.get('origin') or x['start'])
                    return [(stamp(origin+timedelta(minutes=s['start_slot']*15)),
                        stamp(origin+timedelta(minutes=s['end_slot']*15)), tuple(sorted(s['crane_ids']))) for s in p.get('segments', [])]
                if segments(a) != segments(b):
                    fields.append('PROCESSING_WINDOWS_CHANGED')
        if not fields:
            continue
        codes = sorted(set(triggers)) or ['ROLLING_CAPACITY_REPLAN']
        result.append(dict(call_id=cid, changed_fields=fields, before=a, after=b,
            reason={'code': 'OBSERVED_PROGRESS_PRESERVED' if cid in carry else 'REOPTIMISED_REMAINING_HORIZON',
                'message': 'Keep the observed berth and crane bundle; revise remaining completion under current calendars.' if cid in carry else
                    'Reoptimise remaining demand against changed inputs with reassignment penalties and the freeze window.',
                'trigger_kinds': codes}, operator_action='Review the new windows and communicate any revised ETA/berth instruction.'))
    return result


def build(data, assignments, shifts, diagnostics, forecast_alerts, lifecycle_alerts,
          previous_assignments=(), triggers=(), operational_changes=()):
    data = prepare(data)
    r = Resources(data)
    carry = {c['call_id']: c for c in data['carry_in']}
    completed = {e['call_id'] for e in data.get('known_call_observations', []) if e['kind'] == 'departure'}
    ledger = [internal(a, r) for a in assignments]
    frozen, _, errors = fixed_options(r)
    ledger.extend(o for o in frozen if o['call_id'] not in {a['call_id'] for a in ledger})
    public = [r.public(o) for o in ledger if o['planned_moves'] > 0]
    by_call = {a['call_id']: a for a in public}
    valid, yard_rows, _ = yard_trace(r, ledger, diagnostics.get('gate_plan'))
    yard = defaultdict(list)
    for row in yard_rows:
        yard[row['terminal_id']].append(row)
    conflicts = list(diagnostics.get('infeasibility_explanations', []))
    conflicts.extend(e for e in errors if e not in conflicts)
    if not valid:
        conflicts.append(dict(code='UNSAFE_YARD_PROJECTION', message='The fixed reservation yard projection cannot be certified; do not dispatch the plan.'))
    changes = material_changes(previous_assignments, public, triggers, carry, completed) if previous_assignments else []
    documents = []

    def vessel(cid):
        c = r.calls[cid]
        v = r.vessels[c['vessel_id']]
        return dict(call_id=cid, vessel_id=v['id'], vessel_name=v.get('name', v['id']), terminal_id=c['terminal_id'],
            port_id=r.terminals[c['terminal_id']]['port_id'], scheduled_eta=c['scheduled_eta'],
            actual_arrival=r.arrivals.get(cid), priority=c['priority'], cargo_type=c['cargo_type'])

    for shift in shifts:
        begin, end = parse(shift['start']), parse(shift['end'])
        incoming, waiting, berthing, departing = [], [], [], []
        for cid, c in sorted(r.calls.items()):
            if cid in completed:
                continue
            arrival = parse(r.arrivals.get(cid, c['scheduled_eta']))
            a = by_call.get(cid)
            if begin <= arrival < end and cid not in carry:
                incoming.append(vessel(cid))
            start = parse(a['start']) if a else r.times[-1]
            if cid not in carry and max(begin, arrival) < min(end, start):
                waiting.append(dict(vessel(cid), waiting_start=stamp(max(begin, arrival)),
                    waiting_end=stamp(min(end, start)), status='SCHEDULED' if a else 'UNRESOLVED_NO_BERTH',
                    expected_wait_hours=a['waiting_minutes']/60 if a else None))
            if a and parse(a['start']) < end and parse(a['end']) > begin:
                berthing.append(vessel(cid))
            if a and begin <= parse(a['end']) < end:
                departing.append(vessel(cid))
        berth_assignments, cranes, handoffs = [], [], []
        for a in public:
            if not (parse(a['start']) < end and parse(a['end']) > begin):
                continue
            tasks = [t for t in shift['tasks'] if t['call_id'] == a['call_id'] and t['task_type'] == 'container_handling']
            crane_hours = sum((parse(t['end'])-parse(t['start'])).total_seconds()/3600*len(t['crane_ids']) for t in tasks)
            processing_hours = sum((parse(t['end'])-parse(t['start'])).total_seconds()/3600 for t in tasks)
            moves = sum(t['planned_moves'] for t in tasks)
            tid = r.berths[a['berth_id']]['terminal_id']
            berth_assignments.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], terminal_id=tid,
                start=a['start'], completion_time=a['completion_time'], departure=a['end'],
                original_started_at=carry[a['call_id']]['started_at'] if a['call_id'] in carry else None,
                planned_moves_in_shift=moves, total_remaining_planned_moves=a['planned_moves']))
            cranes.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], segments=tasks,
                planned_moves=moves, crane_hours=crane_hours,
                expected_moves_per_crane_hour=moves/crane_hours if crane_hours else None,
                expected_moves_per_processing_hour=moves/processing_hours if processing_hours else None,
                inventory_productivity_moves_per_crane_hour={cid:r.cranes[cid]['productivity_moves_per_hour'] for t in tasks for cid in t['crane_ids']}))
            if parse(a['end']) >= end:
                remaining = sum(s['moves']*max(0, s['end_slot']-max(s['start_slot'], round((end-r.origin).total_seconds()/900)))/(s['end_slot']-s['start_slot']) for s in a['execution_profile']['segments'])
                risks = ['LOW_CONFIDENCE_SYNTHETIC_FORECAST']
                if parse(a['completion_time']) <= end:
                    risks.append('AWAIT_DEPARTURE_OR_TIDE_WINDOW')
                if a['waiting_minutes']/60 > 8:
                    risks.append('LONG_WAIT_CUSTOMER_COORDINATION')
                if parse(a['end']) > r.origin+timedelta(hours=72):
                    risks.append('COMPLETION_TAIL_REQUIRES_NEXT_ROLLING_PLAN')
                handoffs.append(dict(call_id=a['call_id'], berth_id=a['berth_id'], at=stamp(end),
                    remaining_moves=remaining, completion_time=a['completion_time'], departure=a['end'],
                    risk_codes=risks, action='Confirm actual completed unload/load moves, retained crane bundle and berth occupancy with the next supervisor.'))
        yard_projections = []
        for cid, observed in carry.items():
            if cid in by_call or cid in completed:
                continue
            berthing.append(vessel(cid))
            tid = r.berths[observed['berth_id']]['terminal_id']
            berth_assignments.append(dict(call_id=cid, berth_id=observed['berth_id'], terminal_id=tid,
                start=data['as_of'], original_started_at=observed['started_at'], completion_time=None, departure=None,
                planned_moves_in_shift=0, total_remaining_planned_moves=observed['remaining_moves']))
            cranes.append(dict(call_id=cid, berth_id=observed['berth_id'], segments=[], planned_moves=0,
                crane_hours=0, expected_moves_per_crane_hour=None, expected_moves_per_processing_hour=None,
                inventory_productivity_moves_per_crane_hour={c:r.cranes[c]['productivity_moves_per_hour'] for c in observed['crane_ids']}))
            handoffs.append(dict(call_id=cid, berth_id=observed['berth_id'], at=stamp(end), remaining_moves=observed['remaining_moves'],
                completion_time=None, departure=None, risk_codes=['UNRESOLVED_STARTED_OPERATION'],
                action='Retain observed berth ownership; confirm actual departure or resolve the unsafe calendar before dispatch.'))
        for tid, terminal in sorted(r.terminals.items()):
            rows = [y for y in yard[tid] if begin <= parse(y['timestamp']) < end]
            previous = [y for y in yard[tid] if parse(y['timestamp']) < begin]
            opening = previous[-1]['closing_teu'] if previous else r.yards[tid]['closing_teu']
            peak = max([opening]+[y['peak_teu'] for y in rows])
            yard_projections.append(dict(terminal_id=tid, port_id=terminal['port_id'], capacity_teu=terminal['yard_capacity_teu'],
                safe_planning_capacity_teu=r.planning_capacity[tid], opening_teu=opening,
                closing_teu=rows[-1]['closing_teu'] if rows else opening, peak_teu=peak,
                peak_occupancy_fraction=peak/terminal['yard_capacity_teu'], projection_certified=valid))
        weather, tides, restrictions = [], [], []
        s, e = round((begin-r.origin).total_seconds()/900), round((end-r.origin).total_seconds()/900)
        for pid in data['port_ids']:
            weather.append(dict(port_id=pid, **{k:v for k,v in r.weather[pid].items() if k not in ('id','port_id')},
                basis='latest_observation_persisted_with_known_calendar_overrides',
                closed_intervals=[dict(start=stamp(r.times[i]), end=stamp(r.times[i+1])) for i in range(s,e) if r.closed[pid][i]]))
            tides.append(dict(port_id=pid, minimum_height_m=min(r.tides[pid][s:e+1]), maximum_height_m=max(r.tides[pid][s:e+1]),
                basis=r.tide_quality[pid], movement_requirements=[dict(call_id=a['call_id'], berth_id=a['berth_id'],
                    required_tide_height_m=r.vessels[r.calls[a['call_id']]['vessel_id']]['draft_m']+r.berths[a['berth_id']]['under_keel_clearance_m']-r.berths[a['berth_id']]['depth_m'])
                    for a in berth_assignments if r.terminals[a['terminal_id']]['port_id']==pid],
                supervisor_action='Check observed tide and visibility before movement; retain the published under-keel and alongside clearance margins.'))
        for cid in sorted(r.cranes):
            blocked = [i for i in range(s,e) if not r.available[cid][i]]
            if blocked:
                restrictions.append(dict(crane_id=cid, berth_id=r.cranes[cid]['berth_id'], unavailable_hours=len(blocked)/4,
                    reasons=sorted({a.get('reason','known_outage') for a in data['availability'] if a['crane_id']==cid and
                        parse(a['start']) < end and (a.get('reason')=='breakdown' or parse(a['end']) > begin)}),
                    action='Do not assign this crane during unavailable slots; require an observed restoration before clearing breakdown restrictions.'))
        for bid in sorted(r.berths):
            blocked=[i for i in range(s,e) if r.berth_closed[bid][i]]
            if blocked:
                restrictions.append(dict(berth_id=bid,unavailable_hours=len(blocked)/4,reasons=['berth_closure'],
                    action='Keep ongoing berth ownership; pause handling and movement during closure. No new entry until the closure clears.'))
        alerts = []
        grouped = defaultdict(list)
        for a in forecast_alerts:
            if begin <= parse(a['timestamp']) < end:
                grouped[a['berth_id']].append(a)
        for bid, rows in sorted(grouped.items()):
            alerts.append(dict(code='FORECAST_CONGESTION', scope='berth', scope_id=bid,
                first_time=min(a['timestamp'] for a in rows), hourly_buckets=len(rows),
                maximum_pressure_ratio=max((a['pressure_ratio'] for a in rows if a['pressure_ratio'] is not None), default=None),
                basis='source_forecast_run', action='Confirm arrivals and berth dispatch; assess holding or a fresh end-to-end what-if before changing routes.'))
        alerts.extend(a for a in lifecycle_alerts if parse(a['expected_start']) < end and parse(a['expected_end']) > begin)
        alerts.extend(dict(code='HIGH_YARD_OCCUPANCY', terminal_id=y['terminal_id'], peak_occupancy_fraction=y['peak_occupancy_fraction'],
            action='Coordinate gate releases and verify staged discharge/load stock before vessel dispatch.') for y in yard_projections if y['peak_occupancy_fraction'] > .85)
        actions = [dict(code='SHIFT_START_RECONCILIATION', owner_role='shift_supervisor', due_at=stamp(begin),
            action='Reconcile actual ETAs, berth occupancy, completed moves, yard stock and crane calendars before dispatch.')]
        actions.extend(dict(code=a['code'] if 'code' in a else a.get('rule_code','CONGESTION_ALERT'), owner_role='shift_supervisor',
            due_at=a.get('first_time', stamp(begin)), action=a.get('action','Review and acknowledge the operational alert; confirm resources before dispatch.')) for a in alerts)
        if handoffs:
            actions.append(dict(code='CONFIRM_HIGH_RISK_HANDOFFS', owner_role='shift_supervisor', due_at=stamp(end),
                action='Exchange measured unload/load progress and retained berth/crane ownership for '+', '.join(h['call_id'] for h in handoffs)+'.'))
        proposed = [c for c in operational_changes if c.get('kind') == 'eta' and c.get('call_id') in r.calls and begin <= parse(c['scheduled_eta']) < end]
        proposed.extend(dict(kind='diversion', call_id=a['call_id'], receiving_terminal_id=a['terminal_id']) for a in berth_assignments
                        if r.terminals[a['terminal_id']]['port_id'] != r.terminals[r.calls[a['call_id']]['terminal_id']]['port_id'])
        documents.append(dict(shift_index=shift['shift_index'], incoming=incoming, waiting=waiting, berthing=berthing, departing=departing,
            berth_assignments=berth_assignments, crane_allocation=cranes, planned_container_moves=sum(c['planned_moves'] for c in cranes),
            projected_yard_occupancy=yard_projections, weather_constraints=weather, tide_constraints=tides,
            maintenance_and_equipment_restrictions=restrictions, high_risk_handoffs=handoffs, congestion_alerts=alerts,
            required_supervisor_actions=actions, plan_changes_requiring_approval=proposed, approved_diversions_or_arrival_changes=[],
            contingency_actions=[dict(trigger='CRANE_FAILURE_OR_UNSAFE_WEATHER', action='Pause affected handling/movement; retain the vessel berth and report measured progress. Replan with the updated outage or weather observation.'),
                dict(trigger='YARD_SAFE_CAPACITY_AT_RISK', action='Hold dispatch/discharge until gate releases and certified staging restore headroom; never exceed the hard yard ceiling.'),
                dict(trigger='ETA_OR_DEADLINE_DEVIATION', action='Update the observed ETA and customer constraints, run the responsible what-if comparison and jointly replan before approving changes.')],
            handover_notes=[f'{h["call_id"]}: retain berth {h["berth_id"]}; {h["remaining_moves"]:.1f} planned moves remain at handoff; confirm actual counters.' for h in handoffs] or
                ['Reconcile outstanding queue, yard stock and resource restrictions; confirm the next supervisor has the latest plan revision.'],
            confidence='LOW', assumptions=['Linear prorating inside each productive crane segment; effective productivity includes weather, conservative yard factor and diminishing crane returns.']))
    return dict(version='rolling-supervisor-plan-v1', as_of=data['as_of'], horizon_hours=72,
        shift_count=9, shift_duration_hours=8, timezone='UTC', confidence='LOW', material_change_threshold_minutes=MATERIAL_MINUTES,
        changes_compared_with_approved_plan=changes, unresolved_conflicts=conflicts,
        assumptions=list(diagnostics.get('assumptions', []))+[
            'Shift boundaries use half-open [start,end) intervals; departure at 72h belongs to the next rolling plan.',
            'Yard occupancy is checked on the full 15-minute resource grid, not inferred from coarse chart samples.',
            'Known weather is propagated from observations with announced calendar overrides; forecasts and tide fits require operator verification.',
            'Synthetic forecast confidence is LOW. Independent routing recommendations are not approved vessel instructions.'],
        incoming_calls_72h=sorted({v['call_id'] for d in documents for v in d['incoming']}),
        waiting_calls_72h=sorted({v['call_id'] for d in documents for v in d['waiting']}),
        completion_tail_call_ids=sorted(a['call_id'] for a in public if parse(a['end']) >= r.origin+timedelta(hours=72))), documents
