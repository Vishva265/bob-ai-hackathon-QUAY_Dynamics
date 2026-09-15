"""Independent safety validation; invalid candidates never become supervisor plans."""
import math
from collections import defaultdict

from app.errors import DomainError
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, SHIFT, TAIL, yard_trace
from app.synthetic.simulator import parse


def validate_schedule(data, assignments, deferred=None, gate_plan=None):
    data = prepare(data)
    r = Resources(data)
    intervals = defaultdict(list)
    options, assigned = [], set()
    carry_ids = {c['call_id'] for c in data['carry_in']}
    committed_ids = {a['call_id'] for a in data['commitments']}
    for a in assignments:
        cid, bid = a['call_id'], a['berth_id']
        if cid in assigned:
            raise DomainError('INVALID_ASSIGNMENT', 'Assignment contains duplicate demand')
        if cid not in r.calls or bid not in r.berths:
            raise DomainError('BROKEN_ASSIGNMENT_REFERENCE', 'Unknown vessel call or berth')
        assigned.add(cid)
        call, b = r.calls[cid], r.berths[bid]
        start, end = parse(a['start']), parse(a['end'])
        completion = parse(a.get('completion_time') or a['end'])
        if not r.origin <= start < completion <= end <= r.times[-1]:
            raise DomainError('INVALID_ASSIGNMENT', 'Assignment contains invalid times or completion precedence')
        s = math.ceil((start-r.origin).total_seconds()/900)
        c = math.ceil((completion-r.origin).total_seconds()/900)
        e = math.ceil((end-r.origin).total_seconds()/900)
        if cid not in carry_ids and not (r.compatible(call, bid, s) and r.compatible(call, bid, e)):
            raise DomainError('INCOMPATIBLE_ASSIGNMENT', 'Berth violates dimensions, cargo, equipment or tide-window restrictions')
        if cid not in carry_ids and s < r.release(call)+math.ceil((r.distance(call, bid) or 0)/r.policy.transit_speed_knots*4):
            raise DomainError('ARRIVAL_ORDER', 'Berthing begins before arrival and routing transit')
        if cid not in carry_ids and (r.berth_closed[bid][min(s, TAIL-1)] or r.berth_closed[bid][min(e, TAIL-1)]):
            raise DomainError('BERTH_CLOSED', 'Vessel movement intersects a known berth closure')
        if cid not in carry_ids and (r.closed[r.terminals[b['terminal_id']]['port_id']][min(s, TAIL-1)] or
                                     r.closed[r.terminals[b['terminal_id']]['port_id']][min(e, TAIL-1)]):
            raise DomainError('STORM_CLOSURE', 'Unsafe wind, visibility or storm at vessel movement time')
        if cid not in carry_ids and a['planned_moves'] != call['unload_moves']+call['load_moves']:
            raise DomainError('DEMAND_ACCOUNTING', 'Accepted vessel does not cover every requested move')
        profile = a.get('execution_profile')
        if not profile:
            # Older approved assignments are immutable historical reservations.
            if cid not in committed_ids:
                raise DomainError('MISSING_EXECUTION_PROFILE', 'An executable crane/processing profile is required')
            profile = dict(segments=[dict(start_slot=s, end_slot=c, crane_ids=a['crane_ids'], shift_index=s//SHIFT, moves=a['planned_moves'])],
                productive_slots=list(range(s, c)), shift_cranes=[len(a['crane_ids']) if s<(i+1)*SHIFT and c>i*SHIFT else 0 for i in range(15)],
                reroute_distance_nm=0, release_slot=s, carry=False, commitment=True)
        segments = profile['segments']
        v = r.vessels[call['vessel_id']]
        counts, moved, previous_end = [0]*15, 0.0, s
        for seg in segments:
            first, last, ids = seg['start_slot'], seg['end_slot'], seg['crane_ids']
            if first < previous_end or not s <= first < last <= c or not ids:
                raise DomainError('PROCESSING_PRECEDENCE', 'Crane processing overlaps itself or violates service boundaries')
            if cid not in carry_ids and first < s+r.policy.berth_entry_buffer_minutes//15:
                raise DomainError('SAFETY_BUFFER', 'Container handling starts before berthing safety buffer')
            previous_end = last
            if len(set(ids)) != len(ids) or len(ids) > min(v['max_cranes'], b['max_cranes']):
                raise DomainError('CRANE_CAPACITY', 'Concurrent crane count exceeds vessel/berth limits')
            for crane_id in ids:
                if crane_id not in r.cranes or r.cranes[crane_id]['berth_id'] != bid:
                    raise DomainError('INCOMPATIBLE_CRANE', 'Crane is missing or attached to another berth')
                if v['required_equipment'] != 'panamax_sts' and r.cranes[crane_id]['equipment'] != 'super_post_panamax_sts':
                    raise DomainError('INCOMPATIBLE_CRANE', 'Crane equipment cannot support vessel')
                if not all(r.available[crane_id][i] for i in range(first, last)):
                    raise DomainError('CRANE_UNAVAILABLE', 'Productive crane assignment intersects a known outage')
                intervals['crane:'+crane_id].append((first, last))
            pid = r.terminals[b['terminal_id']]['port_id']
            if any(r.closed[pid][i] or r.berth_closed[bid][i] for i in range(first, last)):
                raise DomainError('STORM_CLOSURE', 'Container handling intersects a closure')
            for i in range(first, last):
                counts[i//SHIFT] = max(counts[i//SHIFT], len(ids))
            from app.synthetic.simulator import weather_factor, yard_factor
            terminal = r.terminals[b['terminal_id']]
            ceiling = max(r.yards[terminal['id']]['closing_teu'], r.planning_capacity[terminal['id']])
            rate = sum(r.cranes[x]['productivity_moves_per_hour'] for x in ids)*len(ids)**-.18
            rate *= weather_factor(r.weather[pid]['wind_mps'], r.weather[pid]['rain_mm_per_hour'])*yard_factor(ceiling, terminal['yard_capacity_teu'])
            if seg['moves'] < 0 or seg['moves'] > rate*(last-first)/4+1e-6:
                raise DomainError('INSUFFICIENT_PROCESSING_CAPACITY', 'Declared moves exceed crane-hours and conservative productivity')
            moved += seg['moves']
        if abs(moved-a['planned_moves']) > 1e-5:
            raise DomainError('DEMAND_ACCOUNTING', 'Crane profile does not complete required moves')
        if counts != profile['shift_cranes']:
            raise DomainError('CRANE_CAPACITY', 'Shift decision counts disagree with executable segments')
        if cid not in carry_ids and e-c < r.policy.berth_exit_buffer_minutes//15:
            raise DomainError('SAFETY_BUFFER', 'Vessel departure violates service completion safety buffer')
        intervals['berth:'+bid].append((s, e))
        options.append(dict(call_id=cid, berth_id=bid, start_slot=s, completion_slot=c, end_slot=e,
            planned_moves=a['planned_moves'], waiting_minutes=a['waiting_minutes'], crane_ids=a['crane_ids'], execution_profile=profile))
    from app.optimisation.engine import fixed_options
    fixed, _, errors = fixed_options(r)
    if errors:
        raise DomainError('CARRY_IN_NO_COMPLETION', errors[0]['message'])
    for o in fixed:
        if o['call_id'] in assigned:
            continue
        intervals['berth:'+o['berth_id']].append((o['start_slot'], o['end_slot']))
        for seg in o['execution_profile']['segments']:
            for cid in seg['crane_ids']:
                intervals['crane:'+cid].append((seg['start_slot'], seg['end_slot']))
        options.append(o)
    for values in intervals.values():
        values.sort()
        if any(a[1] > b[0] for a, b in zip(values, values[1:])):
            raise DomainError('RESOURCE_OVERLAP', 'Two vessels overlap a berth or productive crane')
    if deferred is not None:
        expected = {c['id'] for c in r.calls.values() if r.release(c)<288} - {a['call_id'] for a in data['commitments']} - carry_ids
        if assigned & set(deferred) or expected != (assigned-carry_ids-committed_ids)|set(deferred):
            raise DomainError('DEMAND_ACCOUNTING', 'Every vessel needs exactly one acceptance or explicit deferral decision')
    valid, traces, _ = yard_trace(r, options, gate_plan)
    if not valid:
        raise DomainError('YARD_CAPACITY', 'Conserved yard staging or gate flows exceed safe hard capacity or become negative')
    return traces
