"""Independent structural, physical and conservation checks for generated data."""
import math
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from .schema import ENUMS, SCHEMA
from .simulator import compatible, parse, stamp, weather_factor, yard_factor


class DataValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Dataset validation failed:\n' + '\n'.join(errors[:30]))


def validate(tables, manifest):
    errors = []
    checks = 0

    def require(condition, message):
        nonlocal checks
        checks += 1
        if not condition:
            errors.append(message)

    def close(a, b):
        return math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-8)

    require(set(tables) == set(SCHEMA), 'Missing or unknown tables')
    if errors:
        raise DataValidationError(errors)
    indexes = {}
    for name, fields in SCHEMA.items():
        rows = tables[name]
        require(len({r.get('id') for r in rows}) == len(rows), f'{name}: duplicate IDs')
        indexes[name] = {r.get('id'): r for r in rows}
        for row in rows:
            require(set(row) == set(fields), f'{name}/{row.get("id")}: incorrect fields')
            for key, field in fields.items():
                value = row.get(key)
                label = f'{name}/{row.get("id")}/{key}'
                if value is None:
                    require(field.nullable, f'{label}: missing required value')
                    continue
                try:
                    if field.kind == 'time':
                        dt = parse(value)
                        require(dt.minute == dt.second == dt.microsecond == 0, f'{label}: not hour aligned')
                    elif field.kind in ('float', 'int'):
                        require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value), f'{label}: not finite numeric')
                        if field.kind == 'int':
                            require(isinstance(value, int), f'{label}: not integer')
                        if (name, key) not in {('ports', 'latitude'), ('ports', 'longitude'), ('tides', 'height_m')}:
                            require(value >= 0, f'{label}: negative quantity')
                    else:
                        require(isinstance(value, str) and bool(value), f'{label}: invalid text')
                    if (name, key) in ENUMS:
                        require(value in ENUMS[(name, key)], f'{label}: invalid enum')
                except (ValueError, TypeError, AttributeError):
                    require(False, f'{label}: invalid typed value or UTC timestamp')
    # Stop here if malformed rows would make arithmetic/reference checks unsafe.
    if errors:
        raise DataValidationError(errors)
    for name, fields in SCHEMA.items():
        for row in tables[name]:
            for key, field in fields.items():
                if field.reference and row[key] is not None:
                    require(row[key] in indexes[field.reference], f'{name}/{row["id"]}: broken reference {key}')
    if errors:
        raise DataValidationError(errors)
    ports, terminals, berths, cranes, vessels, calls = (indexes[n] for n in ('ports', 'terminals', 'berths', 'cranes', 'vessels', 'vessel_calls'))
    cargo = {(r['berth_id'], r['cargo_type']) for r in tables['berth_cargo_compatibility']}
    as_of, start, schedule_end, end = (parse(manifest[k]) for k in ('epoch', 'history_start', 'schedule_end', 'simulation_end'))
    require(as_of-start == timedelta(days=manifest['history_days']), 'History coverage inconsistent')
    require(schedule_end-as_of == timedelta(days=manifest['upcoming_days']), 'Upcoming coverage inconsistent')
    require(end >= schedule_end, 'Simulation misses schedule horizon')
    require(len(ports) >= 4, 'Fewer than four ports')
    for p in ports.values():
        require(-90 <= p['latitude'] <= 90 and -180 <= p['longitude'] <= 180, f'{p["id"]}: invalid coordinates')
        try:
            ZoneInfo(p['timezone'])
        except (KeyError, ValueError):
            require(False, f'{p["id"]}: invalid timezone')
        require(3 <= sum(t['port_id'] == p['id'] for t in terminals.values()) <= 6, f'{p["id"]}: terminal count')
    for t in terminals.values():
        require(t['yard_capacity_teu'] > 0 and t['initial_yard_teu'] <= t['yard_capacity_teu'], f'{t["id"]}: initial yard capacity')
        require(sum(b['terminal_id'] == t['id'] for b in berths.values()) >= 2, f'{t["id"]}: too few berths')
    for b in berths.values():
        require(b['length_m'] > 0 and b['depth_m'] > 0 and b['max_cranes'] > 0, f'{b["id"]}: berth capacity')
    for c in cranes.values():
        require(c['equipment'] == berths[c['berth_id']]['equipment'] and c['productivity_moves_per_hour'] > 0, f'{c["id"]}: crane equipment/productivity')
    for v in vessels.values():
        require(v['length_m'] > 0 and v['draft_m'] > 0 and v['capacity_teu'] > 0 and v['max_cranes'] > 0, f'{v["id"]}: invalid vessel dimensions')
    for call in calls.values():
        v = vessels[call['vessel_id']]
        eta = parse(call['scheduled_eta'])
        require(start <= eta < schedule_end, f'{call["id"]}: ETA outside schedule')
        require(call['period'] == ('historical' if eta < as_of else 'upcoming'), f'{call["id"]}: period leakage')
        require(1 <= call['priority'] <= 5 and 1 <= call['teu_per_move'] <= 2, f'{call["id"]}: priority or mean size')
        require(call['unload_moves'] > call['load_moves'] > 0, f'{call["id"]}: demo requires net-discharge exchange')
        require(call['onboard_teu'] <= v['capacity_teu'] and call['unload_moves']*call['teu_per_move'] <= call['onboard_teu'], f'{call["id"]}: vessel load capacity')
        require(call['onboard_teu']+(call['load_moves']-call['unload_moves'])*call['teu_per_move'] <= v['capacity_teu'], f'{call["id"]}: post-exchange capacity')
        require(any(compatible(v, call, b, cargo, 0) for b in berths.values()), f'{call["id"]}: no compatible berth')

    def unique_keys(table, fields):
        keys = [tuple(r[f] for f in fields) for r in tables[table]]
        require(len(keys) == len(set(keys)), f'{table}: duplicate natural key {fields}')

    for table, fields in [('weather', ('port_id', 'timestamp')), ('tides', ('port_id', 'timestamp')),
                          ('yard_snapshots', ('terminal_id', 'timestamp')), ('call_outcomes', ('call_id',)),
                          ('handling_log', ('call_id', 'timestamp')), ('crane_assignments', ('call_id', 'crane_id')),
                          ('berth_cargo_compatibility', ('berth_id', 'cargo_type'))]:
        unique_keys(table, fields)
    weather = {(r['port_id'], r['timestamp']): r for r in tables['weather']}
    tides = {(r['port_id'], r['timestamp']): r['height_m'] for r in tables['tides']}
    for pid in ports:
        for h in range(int((end-start).total_seconds()/3600)):
            key = (pid, stamp(start+timedelta(hours=h)))
            require(key in weather and key in tides, f'{key}: weather/tide coverage missing')
            if key in weather:
                require(weather[key]['period'] == ('historical_observation' if parse(key[1]) < as_of else 'simulated_future_truth'), f'{key}: weather label leakage')
    if errors:
        raise DataValidationError(errors)
    for table in ('crane_availability', 'disruptions'):
        for row in tables[table]:
            require(parse(row['start']) < parse(row['end']), f'{table}/{row["id"]}: impossible interval')
    events = indexes['disruptions']
    late = {}
    for event in events.values():
        pid = event['port_id']
        if event['terminal_id']:
            require(terminals[event['terminal_id']]['port_id'] == pid, f'{event["id"]}: terminal outside event port')
        if event['crane_id']:
            tid = berths[cranes[event['crane_id']]['berth_id']]['terminal_id']
            require(event['terminal_id'] == tid, f'{event["id"]}: crane outside event terminal')
        if event['kind'] == 'late_arrival':
            require(event['call_id'] is not None, f'{event["id"]}: late event misses call')
            if event['call_id']:
                late[event['call_id']] = event
                call = calls[event['call_id']]
                require(event['start'] == call['scheduled_eta'] and event['terminal_id'] == call['terminal_id'], f'{event["id"]}: late event scope')
                require(close((parse(event['end'])-parse(event['start'])).total_seconds()/3600, event['value']), f'{event["id"]}: delay mismatch')
        if event['kind'] == 'yard_congestion':
            require(event['terminal_id'] is not None and event['value'] <= 1, f'{event["id"]}: gate fraction/scope')
        if event['kind'] == 'storm':
            for (pid2, ts), w in weather.items():
                if pid2 == pid and event['start'] <= ts < event['end']:
                    require(w['wind_mps'] >= event['value'], f'{event["id"]}: storm missing from weather')
    down = defaultdict(set)
    for row in tables['crane_availability']:
        if row['reason'] == 'breakdown':
            require(row['disruption_id'] is not None, f'{row["id"]}: breakdown event absent')
        if row['disruption_id']:
            e = events[row['disruption_id']]
            require(e['kind'] == 'crane_breakdown' and e['crane_id'] == row['crane_id'] and e['start'] == row['start'] and e['end'] == row['end'], f'{row["id"]}: breakdown mismatch')
        tick = parse(row['start'])
        while tick < parse(row['end']):
            down[stamp(tick)].add(row['crane_id'])
            tick += timedelta(hours=1)
    outcomes = {r['call_id']: r for r in tables['call_outcomes']}
    require(set(outcomes) == set(calls), 'Missing completed call outcomes')
    reservations = defaultdict(list)
    for r in tables['crane_assignments']:
        reservations[r['call_id']].append(r)
    berth_intervals, crane_intervals, vessel_intervals = defaultdict(list), defaultdict(list), defaultdict(list)
    for cid, o in outcomes.items():
        call = calls[cid]
        v, b = vessels[call['vessel_id']], berths[o['berth_id']]
        arrival, berth_start, complete, departure = (parse(o[k]) for k in ('actual_arrival', 'berth_start', 'service_completion', 'departure'))
        require(parse(call['scheduled_eta']) <= arrival <= berth_start < complete <= departure < end, f'{cid}: impossible outcome timestamps')
        require(o['actual_arrival'] == (late[cid]['end'] if cid in late else call['scheduled_eta']), f'{cid}: arrival does not match delay event')
        require(o['period'] == ('historical' if departure <= as_of else 'simulated_future_truth'), f'{cid}: future outcome leakage')
        require(close(o['waiting_hours'], (berth_start-arrival).total_seconds()/3600), f'{cid}: waiting mismatch')
        pid = terminals[call['terminal_id']]['port_id']
        tick = berth_start
        while tick < departure:
            require(compatible(v, call, b, cargo, tides.get((pid, stamp(tick)), -100)), f'{cid}: unsafe occupied berth depth/compatibility')
            tick += timedelta(hours=1)
        for ts in (o['berth_start'], o['departure']):
            require(compatible(v, call, b, cargo, tides.get((pid, ts), -100)), f'{cid}: incompatible berth/depth at {ts}')
            w = weather.get((pid, ts), {})
            require(w.get('wind_mps', 100) < 20 and w.get('visibility_m', 0) >= 500, f'{cid}: unsafe arrival/departure')
        rs = reservations[cid]
        require(len(rs) == o['assigned_cranes'] <= min(v['max_cranes'], b['max_cranes']), f'{cid}: crane capacity')
        for r in rs:
            require(cranes[r['crane_id']]['berth_id'] == b['id'], f'{cid}: wrong crane berth')
            require(r['start'] == o['berth_start'] and r['end'] == o['service_completion'], f'{cid}: reservation interval mismatch')
            crane_intervals[r['crane_id']].append((r['start'], r['end']))
        berth_intervals[b['id']].append((o['berth_start'], o['departure']))
        vessel_intervals[v['id']].append((o['actual_arrival'], o['departure']))
    for group in (berth_intervals, crane_intervals, vessel_intervals):
        for rid, intervals in group.items():
            intervals.sort()
            for a, b in zip(intervals, intervals[1:]):
                require(a[1] <= b[0], f'{rid}: overlapping assignments')
    if errors:
        raise DataValidationError(errors)
    logs_by_tick = defaultdict(list)
    totals, crane_hours = defaultdict(float), defaultdict(float)
    log_count = defaultdict(int)
    for r in tables['handling_log']:
        cid, ts = r['call_id'], r['timestamp']
        o, call = outcomes[cid], calls[cid]
        require(o['berth_start'] <= ts < o['service_completion'], f'{r["id"]}: handling outside service')
        live = [cranes[a['crane_id']] for a in reservations[cid] if a['crane_id'] not in down[ts]]
        pid = terminals[call['terminal_id']]['port_id']
        w = weather[(pid, ts)]
        wf = weather_factor(w['wind_mps'], w['rain_mm_per_hour'])
        if not compatible(vessels[call['vessel_id']], call, berths[o['berth_id']], cargo, tides[(pid, ts)]):
            wf = 0
        require(r['active_cranes'] == len(live) and close(r['base_rate'], sum(c['productivity_moves_per_hour'] for c in live)), f'{r["id"]}: active crane/rate mismatch')
        require(close(r['weather_factor'], wf), f'{r["id"]}: weather factor mismatch')
        require(close(r['coordination_factor'], len(live)**-.18 if live else 0), f'{r["id"]}: diminishing returns mismatch')
        for field in ('weather_factor', 'yard_factor', 'coordination_factor', 'productive_fraction'):
            require(0 <= r[field] <= 1, f'{r["id"]}: factor range')
        require(close(r['handled_moves'], r['base_rate']*r['weather_factor']*r['yard_factor']*r['coordination_factor']*r['productive_fraction']), f'{r["id"]}: causal throughput mismatch')
        n = call['unload_moves']+call['load_moves']
        require(close(r['inbound_teu'], r['handled_moves']*call['teu_per_move']*call['unload_moves']/n) and close(r['outbound_teu'], r['handled_moves']*call['teu_per_move']*call['load_moves']/n), f'{r["id"]}: moves/TEU mismatch')
        totals[cid] += r['handled_moves']
        crane_hours[cid] += r['active_cranes']*r['productive_fraction']
        log_count[cid] += 1
        logs_by_tick[(call['terminal_id'], ts)].append(r)
    for cid, o in outcomes.items():
        require(close(totals[cid], calls[cid]['unload_moves']+calls[cid]['load_moves']), f'{cid}: incomplete/excess handling')
        require(close(crane_hours[cid], o['crane_hours']), f'{cid}: crane-hours mismatch')
        require(log_count[cid] == int((parse(o['service_completion'])-parse(o['berth_start'])).total_seconds()/3600), f'{cid}: missing handling intervals')
    previous = {tid: t['initial_yard_teu'] for tid, t in terminals.items()}
    yards = sorted(tables['yard_snapshots'], key=lambda r: (r['timestamp'], r['terminal_id']))
    require(len(yards) == len(terminals)*int((end-start).total_seconds()/3600), 'Yard hourly coverage missing')
    call_outcomes_by_terminal = defaultdict(list)
    for o in outcomes.values():
        call_outcomes_by_terminal[calls[o['call_id']]['terminal_id']].append(o)
    for y in yards:
        tid, ts = y['terminal_id'], y['timestamp']
        t = terminals[tid]
        capacity = t['yard_capacity_teu']
        require(start <= parse(ts) < end, f'{y["id"]}: yard timestamp outside coverage')
        require(close(y['opening_teu'], previous[tid]), f'{y["id"]}: broken inventory continuity')
        require(0 <= y['closing_teu'] <= capacity+1e-6, f'{y["id"]}: yard capacity violation')
        factor = min([e['value'] for e in events.values() if e['kind'] == 'yard_congestion' and e['terminal_id'] == tid and e['start'] <= ts < e['end']] or [1])
        expected_gate = min(t['gate_capacity_teu_per_hour']*factor, max(0, y['opening_teu']-capacity*.35))
        require(close(y['gate_outbound_teu'], expected_gate), f'{y["id"]}: gate outflow mismatch')
        inventory = y['opening_teu']-y['gate_outbound_teu']
        rows = sorted(logs_by_tick[(tid, ts)], key=lambda r: outcomes[r['call_id']]['berth_id'])
        for r in rows:
            require(close(r['yard_factor'], yard_factor(inventory, capacity)), f'{r["id"]}: occupancy productivity mismatch')
            inventory += r['inbound_teu']-r['outbound_teu']
            require(0 <= inventory <= capacity+1e-6, f'{r["id"]}: intermediate yard capacity violation')
        require(close(y['inbound_teu'], sum(r['inbound_teu'] for r in rows)) and close(y['outbound_teu'], sum(r['outbound_teu'] for r in rows)), f'{y["id"]}: vessel flows mismatch')
        require(close(y['closing_teu'], inventory), f'{y["id"]}: yard mass balance violation')
        queue = sum(o['actual_arrival'] <= ts <= o['berth_start'] for o in call_outcomes_by_terminal[tid])
        require(y['queued_vessels'] == queue, f'{y["id"]}: queue count mismatch')
        previous[tid] = y['closing_teu']
    if errors:
        raise DataValidationError(errors)
    return dict(valid=True, checks=checks, errors=0, rows=sum(len(r) for r in tables.values()))
