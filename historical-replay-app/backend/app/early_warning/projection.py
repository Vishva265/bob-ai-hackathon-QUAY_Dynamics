"""Quarter-hour FIFO dispatch projection, not an optimised or calibrated forecast.

Uses only published schedules, observations known at origin and known calendars.
Weather and observed gate throughput persist; no future synthetic truth is read.
"""
from collections import defaultdict
from datetime import timedelta

from app.early_warning.rules import RULES, evaluate, hotspot_windows
from app.synthetic.simulator import compatible, parse, weather_factor, yard_factor

LEVELS = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')


def project(data, predictions, waiting, observations, gate_rates, rules, as_of):
    terminals = {t['id']: t for t in data['terminals']}
    berths = {b['id']: b for b in data['berths']}
    cranes = {c['id']: c for c in data['cranes']}
    vessels = {v['id']: v for v in data['vessels']}
    weather = {w['port_id']: w for w in data['weather']}
    yard_rows = {y['terminal_id']: y for y in data['yards']}
    stock = {tid: y['closing_teu'] for tid, y in yard_rows.items()}
    cargo = {(c['berth_id'], c['cargo_type']) for c in data['cargo']}
    events = {(e['call_id'], e['kind']): e for e in observations if parse(e['timestamp']) <= as_of}
    carried = {c['call_id']: c for c in data['carry_in']}
    commitments = {a['call_id']: a for a in data['commitments']}
    jobs = []
    for call in data['calls']:
        cid = call['id']
        if (cid, 'departure') in events:
            continue
        vessel = vessels[call['vessel_id']]
        candidates = sorted(b['id'] for b in berths.values() if compatible(vessel, call, b, cargo, -1.3))
        arrival = parse(events[(cid, 'arrival')]['timestamp']) if (cid, 'arrival') in events else parse(call['scheduled_eta'])
        carry = carried.get(cid)
        commitment = commitments.get(cid)
        fixed = carry['berth_id'] if carry else commitment['berth_id'] if commitment else None
        if not fixed and (cid, 'berth_start') in events:
            fixed = events[(cid, 'berth_start')]['berth_id']
        if fixed:
            # Existing in-progress work is an observed placement, not a new allocation.
            candidates = [fixed]
        total = call['unload_moves'] + call['load_moves']
        jobs.append(dict(call=call, vessel=vessel, candidates=candidates, arrival=arrival,
            remaining=carry['remaining_moves'] if carry else total, total=total,
            berth=fixed if carry or (cid, 'berth_start') in events else None,
            fixed=fixed, commitment=commitment, complete=False,
            wait=waiting.get(cid, {}).get('prediction', 0.0), unsupported_wait=cid not in waiting))
    jobs.sort(key=lambda j: (j['arrival'], j['call']['priority'], j['call']['id']))
    berth_groups = {('berth', bid): [bid] for bid in berths}
    berth_groups.update({('terminal', tid): [b['id'] for b in berths.values() if b['terminal_id'] == tid] for tid in terminals})
    berth_groups.update({('port', pid): [b['id'] for b in berths.values() if terminals[b['terminal_id']]['port_id'] == pid] for pid in data['port_ids']})
    rows_by_scope = defaultdict(list)
    outages = []
    for a in data['availability']:
        start, end = parse(a['start']), parse(a['end'])
        if a['reason'] == 'breakdown':
            if start > as_of:  # future failures are not known inputs
                continue
            end = as_of + timedelta(hours=72)  # repair completion is unknown
        outages.append((a['crane_id'], start, end))
    for hour in range(72):
        timestamp = as_of + timedelta(hours=hour)
        occupied = defaultdict(float)
        busy_cranes = defaultdict(float)
        available_cranes = defaultdict(float)
        queued = defaultdict(float)
        waits = defaultdict(float)
        warnings = defaultdict(set)
        yard_mean = defaultdict(float)
        for quarter in range(4):
            ts = timestamp + timedelta(minutes=quarter * 15)
            down = {cid for cid, start, end in outages if start < ts + timedelta(minutes=15) and end > ts}
            blocked_ports = {pid for pid in data['port_ids'] if weather_factor(weather[pid]['wind_mps'], weather[pid]['rain_mm_per_hour']) == 0
                or any(e['kind'] == 'storm' and e['port_id'] == pid and parse(e['start']) < ts + timedelta(minutes=15)
                       and parse(e['end']) > ts for e in data['disruptions'])}
            blocked_berths = {c['berth_id'] for c in data.get('berth_closures', []) if parse(c['start']) < ts + timedelta(minutes=15) and parse(c['end']) > ts}
            reserved = {a['berth_id']: a['call_id'] for a in data['commitments']
                        if parse(a['start']) < ts + timedelta(minutes=15) and parse(a['end']) > ts}
            for tid, t in terminals.items():
                stock[tid] -= min(stock[tid], max(0, gate_rates.get(tid, 0)) / 4)
            active = {j['berth']: j for j in jobs if j['berth'] and not j['complete']}
            for job in jobs:
                if job['complete'] or job['berth'] or job['arrival'] >= ts + timedelta(minutes=15):
                    continue
                commitment = job['commitment']
                if commitment and parse(commitment['start']) >= ts + timedelta(minutes=15):
                    continue
                choices = [bid for bid in job['candidates'] if bid not in active and bid not in blocked_berths
                           and reserved.get(bid, job['call']['id']) == job['call']['id']
                           and terminals[berths[bid]['terminal_id']]['port_id'] not in blocked_ports]
                choices = [bid for bid in choices if any(c['berth_id'] == bid and c['id'] not in down
                                                       and (job['vessel']['required_equipment'] == 'panamax_sts' or c['equipment'] == 'super_post_panamax_sts') for c in cranes.values())]
                if choices:
                    bid = max(choices, key=lambda bid: (sum(c['productivity_moves_per_hour'] for c in cranes.values()
                                                          if c['berth_id'] == bid and c['id'] not in down), bid))
                    job['berth'] = bid
                    job['wait'] = max(job['wait'], (max(ts, job['arrival']) - job['arrival']).total_seconds() / 3600)
                    active[bid] = job
            for bid, b in berths.items():
                tid = b['terminal_id']
                pid = terminals[tid]['port_id']
                live = [c for c in cranes.values() if c['berth_id'] == bid and c['id'] not in down]
                if bid in blocked_berths:
                    warnings[bid].add('BERTH_CLOSURE')
                    live = []
                available_cranes[bid] += len(live) / 4
                if any(c['berth_id'] == bid and c['id'] in down for c in cranes.values()):
                    warnings[bid].add('KNOWN_CRANE_DOWNTIME')
                w = weather[pid]
                closed = any(e['kind'] == 'storm' and e['port_id'] == pid
                             and parse(e['start']) < ts + timedelta(minutes=15) and parse(e['end']) > ts for e in data['disruptions'])
                wf = 0 if closed else weather_factor(w['wind_mps'], w['rain_mm_per_hour'])
                if wf < 1:
                    warnings[bid].add('WIND_OR_STORM_REDUCES_PRODUCTIVITY')
                job = active.get(bid)
                if any(j['commitment'] and j['fixed'] == bid and not j['complete'] and j['berth'] != bid
                       and parse(j['commitment']['start']) < ts + timedelta(minutes=15) for j in jobs):
                    warnings[bid].add('APPROVED_COMMITMENT_AT_RISK')
                if job:
                    occupied[bid] += .25
                    compatible_cranes = sorted((c for c in live if (job['vessel']['required_equipment'] == 'panamax_sts' or c['equipment'] == 'super_post_panamax_sts')),
                                               key=lambda c: (-c['productivity_moves_per_hour'], c['id']))
                    if job['commitment']:
                        compatible_cranes = [c for c in compatible_cranes if c['id'] in job['commitment']['crane_ids']]
                    count = min(len(compatible_cranes), b['max_cranes'], job['vessel']['max_cranes'])
                    yf = yard_factor(stock[tid], terminals[tid]['yard_capacity_teu'])
                    rate = sum(c['productivity_moves_per_hour'] for c in compatible_cranes[:count]) * (count ** -.18 if count else 0) * wf * yf
                    fraction = max(0, min(.25, (ts + timedelta(minutes=15) - max(ts, job['arrival'])).total_seconds() / 3600))
                    moves = min(job['remaining'], rate * fraction)
                    net_teu = (job['call']['unload_moves'] - job['call']['load_moves']) / max(1, job['total']) * job['call']['teu_per_move']
                    if net_teu > 0:
                        moves = min(moves, max(0, terminals[tid]['yard_capacity_teu'] - stock[tid]) / net_teu)
                    elif net_teu < 0:
                        moves = min(moves, stock[tid] / -net_teu)
                    if rate > 0:
                        busy_cranes[bid] += count * moves / rate
                    if job['remaining'] > 0 and moves == 0:
                        warnings[bid].add('HANDLING_BLOCKED_BY_RESOURCES_OR_YARD')
                    stock[tid] = min(terminals[tid]['yard_capacity_teu'], max(0, stock[tid] + moves * net_teu))
                    job['remaining'] -= moves
                    if job['remaining'] <= 1e-8:
                        job['complete'] = True  # released at next dispatch interval
                for job in jobs:
                    if job['complete'] or job['berth'] or job['arrival'] >= ts + timedelta(minutes=15):
                        continue
                    targets = job['candidates'] or [key for key, value in berths.items() if value['terminal_id'] == job['call']['terminal_id']]
                    if bid in targets:
                        weight = .25 / len(targets)
                        queued[bid] += weight
                        waits[bid] += weight * max(job['wait'], (ts + timedelta(minutes=15) - job['arrival']).total_seconds() / 3600)
                        if not job['candidates']:
                            warnings[bid].add('NO_COMPATIBLE_BERTH')
                        if job['unsupported_wait']:
                            warnings[bid].add('QUEUE_WAIT_USES_ELAPSED_TIME_WITHOUT_VESSEL_MODEL')
            for tid in terminals:
                yard_mean[tid] += stock[tid] / 4
        for (scope, scope_id), bids in berth_groups.items():
            if not bids:
                continue
            tids = sorted({berths[bid]['terminal_id'] for bid in bids})
            pid = terminals[tids[0]]['port_id']
            tid = scope_id if scope == 'terminal' else tids[0] if scope == 'berth' else None
            pred_key = (scope, scope_id, timestamp) if scope != 'berth' else ('terminal', tid, timestamp)
            pred = predictions[pred_key]
            causes = sorted(set().union(*(warnings[bid] for bid in bids)))
            confidence_reasons = []
            if pred['upper'] - pred['lower'] > rules.maximum_uncertainty_width:
                confidence_reasons.append('Wide model event-error band')
            age = max((as_of - parse(weather[pid]['timestamp'])).total_seconds() / 3600,
                      max((as_of - (parse(yard_rows[t]['timestamp']) + timedelta(hours=1))).total_seconds() / 3600 for t in tids))
            if age + hour > rules.maximum_observation_age_hours:
                confidence_reasons.append('Persisted weather/yard assumptions exceed observation-age limit at target hour')
            if scope == 'berth':
                confidence_reasons.append('Berth probability is an inherited terminal prior, not a calibrated berth prediction')
            if any('WITHOUT_VESSEL_MODEL' in cause or cause == 'NO_COMPATIBLE_BERTH' for cause in causes):
                confidence_reasons.append('Unmodelled overdue or incompatible queue demand')
            count = sum(queued[bid] for bid in bids)
            current_moves = previous_moves = 0.0
            for job in jobs:
                if job['call']['terminal_id'] not in tids:
                    continue
                weight = 1 / len(job['candidates']) if scope == 'berth' and scope_id in job['candidates'] else 0 if scope == 'berth' else 1
                eta = parse(job['call']['scheduled_eta'])
                if timestamp <= eta < timestamp + timedelta(hours=rules.arrival_window_hours):
                    current_moves += job['total'] * weight
                if timestamp - timedelta(hours=rules.arrival_window_hours) <= eta < timestamp:
                    previous_moves += job['total'] * weight
            row = dict(scope=scope, scope_id=scope_id, port_id=pid, terminal_id=tid,
                berth_id=scope_id if scope == 'berth' else None, timestamp=timestamp,
                berth_utilisation=sum(occupied[bid] for bid in bids) / len(bids),
                queue_length=count, average_wait_hours=sum(waits[bid] for bid in bids) / count if count else 0,
                yard_occupancy=sum(yard_mean[t] for t in tids) / sum(terminals[t]['yard_capacity_teu'] for t in tids),
                crane_utilisation=sum(busy_cranes[bid] for bid in bids) / sum(available_cranes[bid] for bid in bids) if sum(available_cranes[bid] for bid in bids) else 0,
                congestion_probability=pred['prediction'], probability_lower=pred['lower'], probability_upper=pred['upper'],
                probability_basis='terminal_model_prior' if scope == 'berth' else 'trained_scope_model',
                model_version=pred['model_version'], confidence_level='LOW' if confidence_reasons else 'HIGH' if pred['upper'] - pred['lower'] <= .25 else 'MEDIUM',
                confidence_reasons=confidence_reasons, arrival_workload_ratio=current_moves / max(previous_moves, 1),
                arrival_workload_increase_moves=max(0, current_moves - previous_moves),
                main_causes=[dict(code=c, message=c.replace('_', ' ').lower(), evidence={}) for c in causes],
                prediction_timestamp=pred['prediction_timestamp'])
            breaches = evaluate(row, rules)
            physical = [r for r in evaluate(row, rules.model_copy(update={'enabled': list(RULES)})) if r['code'] != 'LOW_CONFIDENCE']
            ml_level = pred['level'] if scope != 'berth' else 'LOW'
            level = LEVELS[max(LEVELS.index(ml_level), 3 if row['queue_length'] >= 4 or row['yard_occupancy'] >= .95 else 2 if physical else 1 if row['queue_length'] > 0 else 0)]
            row.update(congestion_severity=level, is_hotspot=level in ('HIGH', 'CRITICAL'), rule_breaches=breaches)
            row['main_causes'].extend(physical + [r for r in breaches if r['code'] == 'LOW_CONFIDENCE'])
            if count > 0:
                row['main_causes'].append(dict(code='PROJECTED_QUEUE', message='Arrival workload exceeds immediately compatible dispatch capacity',
                    evidence=dict(queue_length=count, average_wait_hours=row['average_wait_hours'], unit='vessels and hours')))
            if row['yard_occupancy'] >= .85:
                row['main_causes'].append(dict(code='YARD_HANDLING_SLOWDOWN', message='Shared yard inventory reduces handling productivity',
                    evidence=dict(occupancy=row['yard_occupancy'], unit='fraction', terminal_ids=tids)))
            if scope != 'berth' and ml_level in ('HIGH', 'CRITICAL'):
                row['main_causes'].append(dict(code='MODEL_CONGESTION', message='Trained model predicts high or critical conditions',
                    evidence=dict(level=ml_level, probability=pred['prediction'], factors=pred['factors'])))
            if scope == 'berth':
                row['main_causes'].append(dict(code='TERMINAL_MODEL_PRIOR', message='Shared terminal congestion probability; review local resource projection', evidence=dict(terminal_id=tid)))
            rows_by_scope[(scope, scope_id)].append(row)
    summaries = []
    for (scope, scope_id), rows in sorted(rows_by_scope.items()):
        windows = hotspot_windows(rows)
        first = windows[0] if windows else None
        for row in rows:
            row['first_expected_hotspot_time'] = first['start'] if first else None
            row['expected_hotspot_duration_hours'] = first['duration_hours'] if first else 0
        summaries.append(dict(scope=scope, scope_id=scope_id, port_id=rows[0]['port_id'],
            first_expected_hotspot_time=first['start'] if first else None,
            expected_hotspot_duration_hours=first['duration_hours'] if first else 0,
            total_hotspot_hours=sum(w['duration_hours'] for w in windows), windows=windows,
            peak_queue_length=max(r['queue_length'] for r in rows), peak_wait_hours=max(r['average_wait_hours'] for r in rows),
            low_confidence_hours=sum(r['confidence_level'] == 'LOW' for r in rows)))
    return [row for rows in rows_by_scope.values() for row in rows], summaries
