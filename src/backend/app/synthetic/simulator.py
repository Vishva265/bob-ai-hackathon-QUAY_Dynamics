"""Hourly discrete-event simulator with explicit, auditable resource accounting."""
import hashlib
import math
import random
from datetime import datetime, timedelta, timezone

from .schema import SCHEMA

VERSION = '2.0.0'
SCENARIOS = {
    'normal_operations': 'Normal Operations',
    'arrival_surge': 'Arrival Surge',
    'storm_crane_breakdown': 'Storm + Crane Breakdown',
}
HOUR = timedelta(hours=1)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def parse(value: str | datetime) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError('Timestamps must explicitly use UTC')
    return dt


def stream(seed: int, name: str) -> random.Random:
    return random.Random(int.from_bytes(hashlib.sha256(f'{seed}:{name}'.encode()).digest()[:8]))


def weather_factor(wind: float, rain: float) -> float:
    if wind >= 20:
        return 0.0
    return max(0.35, 1 - max(0, wind - 10) * 0.045) * max(0.75, 1 - rain * 0.015)


def yard_factor(inventory: float, capacity: float) -> float:
    return 1 - 0.75 * (inventory / capacity) ** 3


def effective_rate(rates: list[float], wind: float, rain: float, inventory: float, capacity: float) -> float:
    if not rates:
        return 0.0
    return sum(rates) * len(rates) ** -0.18 * weather_factor(wind, rain) * yard_factor(inventory, capacity)


def compatible(vessel, call, berth, cargo, tide):
    return (
        call['terminal_id'] == berth['terminal_id']
        and vessel['length_m'] <= berth['length_m']
        and vessel['draft_m'] + berth['under_keel_clearance_m'] <= berth['depth_m'] + tide
        and (vessel['required_equipment'] == 'panamax_sts' or berth['equipment'] == 'super_post_panamax_sts')
        and (berth['id'], call['cargo_type']) in cargo
    )


def generate(seed=42, epoch='2026-09-13T00:00:00Z', history_days=60, upcoming_days=7,
             scenario='normal_operations'):
    """Return normalized tables. All randomness has stable named streams."""
    if scenario not in SCENARIOS:
        raise ValueError('Unknown scenario')
    as_of = parse(epoch)
    if as_of.minute or as_of.second or as_of.microsecond or as_of.hour:
        raise ValueError('Epoch must be midnight UTC')
    if history_days < 1 or upcoming_days < 1:
        raise ValueError('Day counts must be positive')
    start = as_of - timedelta(days=history_days)
    schedule_end = as_of + timedelta(days=upcoming_days)
    # Tail permits service completion; inputs extend across the entire tail.
    end = schedule_end + timedelta(days=35)
    tables = {table: [] for table in SCHEMA}
    rng = stream(seed, 'infrastructure')
    # P01/P02 form a nearby regional relief pair so a responsible cross-port
    # diversion can be demonstrated.  P03/P04 retain the wider network view.
    locations = [('Saffron Bay', 18.9, 72.9, 'Asia/Kolkata'),
                 ('Konkan Gateway', 18.74, 72.96, 'Asia/Kolkata'),
                 ('Atlantic Reach', 51.9, 4.1, 'Europe/Amsterdam'),
                 ('Pacific Haven', 33.7, -118.2, 'America/Los_Angeles')]
    for p, (name, lat, lon, tz) in enumerate(locations):
        port_id = f'P{p+1:02}'
        tables['ports'].append(dict(id=port_id, name=name, latitude=lat, longitude=lon, timezone=tz))
        for t in range(3 + p):
            tid = f'{port_id}-T{t+1:02}'
            capacity = rng.randrange(5500, 8501, 500)
            tables['terminals'].append(dict(id=tid, port_id=port_id, name=f'Terminal {t+1}',
                yard_capacity_teu=capacity, initial_yard_teu=capacity * rng.uniform(.48, .62),
                gate_capacity_teu_per_hour=rng.uniform(90, 130)))
            for b in range(2 + t % 2):
                bid = f'{tid}-B{b+1}'
                length, depth, n = [(450, 17.5, 5), (350, 14.8, 4), (240, 11.8, 3)][b]
                equipment = 'super_post_panamax_sts' if b == 0 else 'panamax_sts'
                tables['berths'].append(dict(id=bid, terminal_id=tid, length_m=length, depth_m=depth,
                    under_keel_clearance_m=.5, equipment=equipment, max_cranes=n))
                for cargo in ['general'] + (['reefer', 'hazardous'] if b == 0 else ['reefer'] if b == 1 else []):
                    tables['berth_cargo_compatibility'].append(dict(id=f'{bid}-{cargo}', berth_id=bid, cargo_type=cargo))
                for c in range(n):
                    tables['cranes'].append(dict(id=f'{bid}-C{c+1}', berth_id=bid, equipment=equipment,
                        productivity_moves_per_hour=rng.uniform(25, 36)))
    terminals = {r['id']: r for r in tables['terminals']}
    berths = {r['id']: r for r in tables['berths']}
    cranes = {r['id']: r for r in tables['cranes']}
    port_terminals = {p['id']: [t for t in terminals.values() if t['port_id'] == p['id']] for p in tables['ports']}

    def add_call(cid, tid, eta, call_rng):
        size = call_rng.choices(['feeder', 'panamax', 'ultra_large'], [.35, .45, .2])[0]
        dimensions = {'feeder': (170, 210, 7, 9.5, 1800, 3),
                      'panamax': (260, 315, 10, 12.5, 6000, 4),
                      'ultra_large': (355, 410, 14, 15.5, 16000, 5)}
        lo, hi, dlo, dhi, cap, maxc = dimensions[size]
        vid = f'V-{cid}'
        tables['vessels'].append(dict(id=vid, name=f'MV {cid}', size_class=size,
            length_m=call_rng.uniform(lo, hi), draft_m=call_rng.uniform(dlo, dhi), capacity_teu=cap,
            required_equipment='super_post_panamax_sts' if size == 'ultra_large' else 'panamax_sts', max_cranes=maxc))
        onboard = call_rng.randint(int(cap*.45), int(cap*.9))
        moves = call_rng.randint(350, 850) if size == 'feeder' else call_rng.randint(800, 1800) if size == 'panamax' else call_rng.randint(1800, 3000)
        unload = int(moves * .65)
        mean_size = call_rng.uniform(1.35, 1.75)
        onboard = max(onboard, math.ceil(unload*mean_size))
        tables['vessel_calls'].append(dict(id=cid, vessel_id=vid, terminal_id=tid,
            period='historical' if eta < as_of else 'upcoming', scheduled_eta=stamp(eta),
            priority=call_rng.randint(1, 5), cargo_type=call_rng.choices(['general', 'reefer', 'hazardous'], [.65, .25, .1])[0],
            onboard_teu=onboard, unload_moves=unload, load_moves=moves-unload, teu_per_move=mean_size))

    rng = stream(seed, 'calls')
    for day in range(history_days + upcoming_days):
        for port in tables['ports']:
            for n in range(6):
                tid = rng.choice(port_terminals[port['id']])['id']
                eta = start + timedelta(days=day, hours=rng.randrange(24))
                add_call(f'{port["id"]}-D{day:03}-N{n:02}', tid, eta, rng)
    target = port_terminals['P01'][0]['id']
    # Historical pressure episodes are observable training examples.  They are
    # generated before the evaluation origin and do not expose future labels.
    rng = stream(seed, 'historical_surges')
    # Stop at least six weeks before the planning origin so these examples
    # cannot leak into the normal scenario as inherited unfinished work.
    for day in range(7, history_days-42, 14):
        for n in range(8):
            add_call(f'HIST-SURGE-D{day:03}-N{n:02}', target,
                     start+timedelta(days=day, hours=8+n % 4), rng)
    if scenario == 'arrival_surge':
        rng = stream(seed, 'surge_calls')
        for n in range(24):
            add_call(f'SURGE-{n:02}', target, as_of + timedelta(hours=24 + n % 3), rng)

    def event(kind, pid, begin, finish, value, terminal_id=None, crane_id=None, call_id=None):
        row = dict(id=f'D{len(tables["disruptions"])+1:05}', port_id=pid, terminal_id=terminal_id,
                   crane_id=crane_id, call_id=call_id, kind=kind, start=stamp(begin), end=stamp(finish), value=value)
        tables['disruptions'].append(row)
        return row['id']

    rng = stream(seed, 'late_arrivals')
    arrivals = {}
    for call in tables['vessel_calls']:
        eta = parse(call['scheduled_eta'])
        delay = rng.choices([0, 1, 2, 4, 8, 12], [.58, .16, .10, .08, .05, .03])[0]
        arrivals[call['id']] = eta + timedelta(hours=delay)
        if delay:
            tid = call['terminal_id']
            event('late_arrival', terminals[tid]['port_id'], eta, arrivals[call['id']], delay, tid, call_id=call['id'])

    rng = stream(seed, 'events')
    for day in range(4, history_days, 10):
        pid = rng.choice(tables['ports'])['id']
        begin = start + timedelta(days=day, hours=8)
        event('storm', pid, begin, begin + timedelta(hours=18), 24)
        tid = rng.choice(port_terminals[pid])['id']
        event('yard_congestion', pid, begin, begin + timedelta(hours=72), .05, tid)
    if scenario == 'arrival_surge':
        event('arrival_surge', 'P01', as_of+timedelta(hours=24), as_of+timedelta(hours=27), 24, target)
        event('yard_congestion', 'P01', as_of+timedelta(hours=24), as_of+timedelta(hours=120), .02, target)
    if scenario == 'storm_crane_breakdown':
        begin = as_of + timedelta(hours=24)
        event('storm', 'P01', begin, begin + timedelta(hours=36), 26)
        event('yard_congestion', 'P01', begin, begin + timedelta(hours=96), .02, target)

    rng = stream(seed, 'crane_calendars')
    for crane in tables['cranes']:
        bid = crane['berth_id']
        tid = berths[bid]['terminal_id']
        pid = terminals[tid]['port_id']
        # Stable maintenance throughout history, schedule and completion tail.
        for day in range(rng.randrange(10), history_days + upcoming_days + 35, 14):
            begin = start + timedelta(days=day, hours=rng.randrange(24))
            tables['crane_availability'].append(dict(id=f'A{len(tables["crane_availability"])+1:06}',
                crane_id=crane['id'], start=stamp(begin), end=stamp(begin+timedelta(hours=6)), reason='maintenance', disruption_id=None))
        if rng.random() < .25:
            begin = start + timedelta(hours=rng.randrange(max(1, history_days*24-12)))
            did = event('crane_breakdown', pid, begin, begin+timedelta(hours=12), 1, tid, crane['id'])
            tables['crane_availability'].append(dict(id=f'A{len(tables["crane_availability"])+1:06}',
                crane_id=crane['id'], start=stamp(begin), end=stamp(begin+timedelta(hours=12)), reason='breakdown', disruption_id=did))
        if scenario == 'storm_crane_breakdown' and tid == target and int(crane['id'][-1]) <= 3:
            begin = as_of + timedelta(hours=20)
            did = event('crane_breakdown', pid, begin, begin+timedelta(hours=64), 1, tid, crane['id'])
            tables['crane_availability'].append(dict(id=f'A{len(tables["crane_availability"])+1:06}',
                crane_id=crane['id'], start=stamp(begin), end=stamp(begin+timedelta(hours=64)), reason='breakdown', disruption_id=did))

    storms = [r for r in tables['disruptions'] if r['kind'] == 'storm']
    yard_events = [r for r in tables['disruptions'] if r['kind'] == 'yard_congestion']
    unavailable = {}
    for row in tables['crane_availability']:
        tick = parse(row['start'])
        while tick < parse(row['end']):
            unavailable.setdefault(stamp(tick), set()).add(row['crane_id'])
            tick += HOUR
    conditions, tides = {}, {}
    rng = stream(seed, 'weather')
    ticks = int((end-start).total_seconds()/3600)
    for h in range(ticks):
        tick = start + h*HOUR
        ts = stamp(tick)
        for p, port in enumerate(tables['ports']):
            pid = port['id']
            wind = max(0, 6+3*math.sin(h/19+p)+rng.gauss(0, 1.4))
            rain = rng.uniform(0, 4) if rng.random() < .14 else 0
            visibility = rng.uniform(3500, 15000)
            for storm in storms:
                if storm['port_id'] == pid and storm['start'] <= ts < storm['end']:
                    wind = max(wind, storm['value'])
                    rain, visibility = 14, 400
            tide = 1.1*math.sin(2*math.pi*h/12.42+p) + .12*math.sin(2*math.pi*h/(24*14))
            weather = dict(id=f'W-{pid}-{h:05}', port_id=pid, timestamp=ts,
                period='historical_observation' if tick < as_of else 'simulated_future_truth',
                wind_mps=wind, rain_mm_per_hour=rain, visibility_m=visibility)
            tables['weather'].append(weather)
            tables['tides'].append(dict(id=f'TIDE-{pid}-{h:05}', port_id=pid, timestamp=ts, height_m=tide))
            conditions[(pid, ts)] = weather
            tides[(pid, ts)] = tide

    calls = {r['id']: r for r in tables['vessel_calls']}
    vessels = {r['id']: r for r in tables['vessels']}
    cargo = {(r['berth_id'], r['cargo_type']) for r in tables['berth_cargo_compatibility']}
    berth_cranes = {bid: [r['id'] for r in tables['cranes'] if r['berth_id'] == bid] for bid in berths}
    pending = sorted(calls, key=lambda cid: (arrivals[cid], cid))
    cursor, queue, active, done = 0, [], {}, set()
    inventory = {tid: t['initial_yard_teu'] for tid, t in terminals.items()}
    outcomes, assignments = {}, {}

    for h in range(ticks):
        tick, next_tick = start+h*HOUR, start+(h+1)*HOUR
        ts = stamp(tick)
        down = unavailable.get(ts, set())
        # Complete visits remain on berth until the next safe departure opportunity.
        for bid, state in list(active.items()):
            cid = state['call_id']
            call, berth = calls[cid], berths[bid]
            pid = terminals[call['terminal_id']]['port_id']
            weather = conditions[(pid, ts)]
            if state['remaining'] <= 1e-8 and weather['wind_mps'] < 20 and weather['visibility_m'] >= 500 and compatible(vessels[call['vessel_id']], call, berth, cargo, tides[(pid, ts)]):
                outcomes[cid]['departure'] = ts
                outcomes[cid]['period'] = 'historical' if tick <= as_of else 'simulated_future_truth'
                done.add(cid)
                del active[bid]
        while cursor < len(pending) and arrivals[pending[cursor]] <= tick:
            queue.append(pending[cursor])
            cursor += 1
        queued = {tid: sum(calls[cid]['terminal_id'] == tid for cid in queue) for tid in terminals}
        # Local terminal priorities, deterministic tie break. No global cross-port queue.
        queue.sort(key=lambda cid: (calls[cid]['priority'], arrivals[cid], cid))
        for cid in list(queue):
            call, vessel = calls[cid], vessels[calls[cid]['vessel_id']]
            tid = call['terminal_id']
            pid = terminals[tid]['port_id']
            weather = conditions[(pid, ts)]
            if weather['wind_mps'] >= 20 or weather['visibility_m'] < 500:
                continue
            candidates = [b for b in berths.values() if b['id'] not in active and compatible(vessel, call, b, cargo, tides[(pid, ts)])]
            candidates.sort(key=lambda b: (b['length_m'], b['id']))
            for berth in candidates:
                available = [c for c in berth_cranes[berth['id']] if c not in down]
                desired = min(vessel['max_cranes'], berth['max_cranes'], max(2, math.ceil((call['unload_moves']+call['load_moves'])/700)))
                if len(available) < min(2, desired):
                    continue
                reserved = available[:desired]
                active[berth['id']] = dict(call_id=cid, cranes=reserved, remaining=float(call['unload_moves']+call['load_moves']))
                outcomes[cid] = dict(id=f'O-{cid}', call_id=cid, berth_id=berth['id'], period='',
                    actual_arrival=stamp(arrivals[cid]), berth_start=ts, service_completion='', departure='',
                    waiting_hours=(tick-arrivals[cid]).total_seconds()/3600, assigned_cranes=len(reserved), crane_hours=0.0)
                assignments[cid] = [dict(id=f'CA-{cid}-{c}', call_id=cid, crane_id=c, start=ts, end='') for c in reserved]
                queue.remove(cid)
                break
        balances = {}
        for tid, terminal in terminals.items():
            factor = min([e['value'] for e in yard_events if e['terminal_id'] == tid and e['start'] <= ts < e['end']] or [1])
            opening = inventory[tid]
            gate = min(terminal['gate_capacity_teu_per_hour']*factor, max(0, opening-terminal['yard_capacity_teu']*.35))
            inventory[tid] -= gate
            balances[tid] = dict(id=f'Y-{tid}-{h:05}', terminal_id=tid, timestamp=ts, opening_teu=opening,
                gate_outbound_teu=gate, inbound_teu=0.0, outbound_teu=0.0, closing_teu=0.0, queued_vessels=queued[tid])
        for bid, state in sorted(active.items()):
            if state['remaining'] <= 1e-8:
                continue
            cid = state['call_id']
            call, berth = calls[cid], berths[bid]
            tid = call['terminal_id']
            pid = terminals[tid]['port_id']
            weather = conditions[(pid, ts)]
            live = [cranes[c] for c in state['cranes'] if c not in down]
            base = sum(c['productivity_moves_per_hour'] for c in live)
            wf = weather_factor(weather['wind_mps'], weather['rain_mm_per_hour'])
            # Under-keel checks on every handling interval, not just berth entry.
            if not compatible(vessels[call['vessel_id']], call, berth, cargo, tides[(pid, ts)]):
                wf = 0.0
            yf = yard_factor(inventory[tid], terminals[tid]['yard_capacity_teu'])
            cf = len(live)**-.18 if live else 0.0
            rate = base*wf*yf*cf
            total = call['unload_moves']+call['load_moves']
            incoming = call['teu_per_move']*call['unload_moves']/total
            outgoing = call['teu_per_move']*call['load_moves']/total
            # Proportional discharge/load exchange; enforce capacity continuously.
            slack = terminals[tid]['yard_capacity_teu']-inventory[tid]
            moves = max(0.0, min(rate, state['remaining'], slack/(incoming-outgoing)))
            inbound, outbound = moves*incoming, moves*outgoing
            inventory[tid] += inbound-outbound
            balances[tid]['inbound_teu'] += inbound
            balances[tid]['outbound_teu'] += outbound
            fraction = moves/rate if rate > 0 else 0.0
            outcomes[cid]['crane_hours'] += len(live)*fraction
            tables['handling_log'].append(dict(id=f'H-{cid}-{h:05}', call_id=cid, timestamp=ts,
                active_cranes=len(live), base_rate=base, weather_factor=wf, yard_factor=yf,
                coordination_factor=cf, productive_fraction=fraction, handled_moves=moves,
                inbound_teu=inbound, outbound_teu=outbound))
            state['remaining'] -= moves
            if state['remaining'] <= 1e-8:
                outcomes[cid]['service_completion'] = stamp(next_tick)
                for row in assignments[cid]:
                    row['end'] = stamp(next_tick)
        for tid, row in balances.items():
            row['closing_teu'] = inventory[tid]
            tables['yard_snapshots'].append(row)
        if len(done) == len(calls) and next_tick >= schedule_end:
            # Keep input coverage through last departure, without an unnecessary long tail.
            tables['weather'] = [r for r in tables['weather'] if r['timestamp'] <= ts]
            tables['tides'] = [r for r in tables['tides'] if r['timestamp'] <= ts]
            break
    if len(done) != len(calls):
        raise ValueError(f'Completion tail exhausted: {len(calls)-len(done)} incomplete calls; no partial dataset written')
    tables['call_outcomes'] = list(outcomes.values())
    tables['crane_assignments'] = [r for cid in assignments for r in assignments[cid]]
    # Calendar/event tails are retained as explicit future inputs even if unused.
    for rows in tables.values():
        rows.sort(key=lambda r: r['id'])
    return tables, dict(generator_version=VERSION, seed=seed, epoch=stamp(as_of),
        history_start=stamp(start), history_days=history_days, upcoming_days=upcoming_days,
        schedule_end=stamp(schedule_end), simulation_end=stamp(next_tick), scenario=scenario,
        scenario_name=SCENARIOS[scenario], tick_minutes=60, synthetic=True)
