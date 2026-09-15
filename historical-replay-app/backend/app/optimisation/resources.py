"""Known calendars, fitted tide windows and executable shift resource profiles."""
import math
from datetime import timedelta
import numpy as np

from app.optimisation.config import OptimisationPolicy
from app.synthetic.simulator import compatible, parse, stamp, weather_factor, yard_factor

SLOTS = 288
TAIL = 480
SHIFT = 32
TEU_SCALE = 100


class Resources:
    def __init__(self, data):
        self.data = data
        self.origin = parse(data['as_of'])
        self.policy = OptimisationPolicy.model_validate(data.get('optimisation_policy', {}))
        self.terminals = {t['id']: t for t in data['terminals']}
        self.berths = {b['id']: b for b in data['berths']}
        self.cranes = {c['id']: c for c in data['cranes']}
        self.vessels = {v['id']: v for v in data['vessels']}
        self.calls = {c['id']: c for c in data['calls']}
        self.arrivals = {}
        for event in data.get('known_call_observations', []):
            if event['kind'] == 'arrival':
                self.arrivals.setdefault(event['call_id'], event['timestamp'])
        self.weather = {w['port_id']: w for w in data['weather']}
        self.yards = {y['terminal_id']: y for y in data['yards']}
        self.planning_capacity = {}
        for tid, t in self.terminals.items():
            discharge = max((c['unload_moves']*c['teu_per_move'] for c in data['calls'] if c['terminal_id'] == tid
                             or self.policy.allow_rerouting), default=0)
            ceiling = max(self.policy.yard_productivity_min_fraction,
                (self.yards[tid]['closing_teu']+discharge)/t['yard_capacity_teu']+self.policy.yard_productivity_headroom_fraction)
            self.planning_capacity[tid] = t['yard_capacity_teu']*min(self.policy.yard_safe_fraction, ceiling)
        # Internal what-if snapshots retain the source plan's conservative yard
        # certificate. Switching a terminal must never weaken its productivity
        # guarantee or increase the yard ceiling used by existing reservations.
        certificates={**self.policy.yard_capacity_certificates,**data.get('_certified_yard_capacities',{})}
        for tid, capacity in certificates.items():
            if tid not in self.terminals or not math.isfinite(capacity) or not 0 < capacity <= self.terminals[tid]['yard_capacity_teu']*self.policy.yard_safe_fraction or capacity < self.yards[tid]['closing_teu']:
                raise ValueError('Invalid source yard capacity certificate')
            self.planning_capacity[tid] = capacity
        self.cargo = {(c['berth_id'], c['cargo_type']) for c in data['cargo']}
        self.available = {cid: [True] * TAIL for cid in self.cranes}
        self.closed = {pid: [False] * TAIL for pid in data['port_ids']}
        self.berth_closed = {bid: [False] * TAIL for bid in self.berths}
        self.tides, self.tide_quality = {}, {}
        self.times = [self.origin + timedelta(minutes=15*i) for i in range(TAIL+1)]
        for closure in data.get('berth_closures', []):
            for i in range(TAIL):
                if parse(closure['start']) < self.times[i+1] and parse(closure['end']) > self.times[i]:
                    self.berth_closed[closure['berth_id']][i] = True
        for a in data['availability']:
            start, end = parse(a['start']), parse(a['end'])
            if a.get('reason') == 'breakdown':
                if start > self.origin:
                    continue
                end = self.times[-1]  # actual future repair time is never assumed
            for i in range(TAIL):
                if start < self.times[i+1] and end > self.times[i]:
                    self.available[a['crane_id']][i] = False
        for pid in data['port_ids']:
            w = self.weather[pid]
            for i in range(TAIL):
                self.closed[pid][i] = weather_factor(w['wind_mps'], w['rain_mm_per_hour']) == 0 or w.get('visibility_m', 10000) < 500 or any(
                    e['kind'] == 'storm' and e['port_id'] == pid and parse(e['start']) < self.times[i+1]
                    and parse(e['end']) > self.times[i] for e in data['disruptions'])
            rows = [r for r in data.get('tide_observations', []) if r['port_id'] == pid and parse(r['timestamp']) <= self.origin]
            if len(rows) >= 12:
                x = np.array([(parse(r['timestamp'])-self.origin).total_seconds()/3600 for r in rows])
                design = np.column_stack([np.ones(len(x)), np.sin(2*np.pi*x/12.42), np.cos(2*np.pi*x/12.42)])
                coef = np.linalg.lstsq(design, np.array([r['height_m'] for r in rows]), rcond=None)[0]
                residual = float(np.max(np.abs(design @ coef - np.array([r['height_m'] for r in rows]))))
                self.tides[pid] = [float(coef[0]+coef[1]*math.sin(2*math.pi*i/4/12.42)+coef[2]*math.cos(2*math.pi*i/4/12.42)-residual-.05) for i in range(TAIL+1)]
                self.tide_quality[pid] = 'observed_harmonic_fit_with_residual_and_0.05m_margin'
            else:
                self.tides[pid] = [-1.3] * (TAIL+1)
                self.tide_quality[pid] = 'conservative_missing_tide_fallback'
        self.low_tide = {pid: min(heights) for pid, heights in self.tides.items()}
        self.home = {bid: sorted((c for c in self.cranes.values() if c['berth_id'] == bid),
                                key=lambda c: (-c['productivity_moves_per_hour'], c['id'])) for bid in self.berths}

    def release(self, call):
        value = self.arrivals.get(call['id'], call['scheduled_eta'])
        return max(0, math.ceil((parse(value)-self.origin).total_seconds()/900))

    def accrued_wait_minutes(self, call):
        value = self.arrivals.get(call['id'], call['scheduled_eta'])
        return max(0, math.ceil((self.origin-parse(value)).total_seconds()/60))

    def compatible(self, call, bid, movement_slot):
        b = self.berths[bid]
        pid = self.terminals[b['terminal_id']]['port_id']
        target = dict(call, terminal_id=b['terminal_id'])
        original_pid = self.terminals[call['terminal_id']]['port_id']
        if b['terminal_id'] != call['terminal_id'] and not (
            (self.policy.allow_rerouting and pid != original_pid) or
            (self.data.get('_recommendation_terminal_switch') and pid == original_pid)):
            return False
        v = self.vessels[call['vessel_id']]
        return b['equipment'] in ('panamax_sts', 'super_post_panamax_sts') and compatible(v, target, b, self.cargo, self.tides[pid][min(TAIL, movement_slot)]) and (
            v['draft_m'] + self.policy.alongside_clearance_m <= b['depth_m'] + self.low_tide[pid])

    def distance(self, call, bid):
        original = self.terminals[call['terminal_id']]['port_id']
        target = self.terminals[self.berths[bid]['terminal_id']]['port_id']
        if original == target:
            return 0.0
        ports = {p['id']: p for p in self.data.get('routing_ports', [])}
        if original not in ports or target not in ports:
            return None
        a, b = ports[original], ports[target]
        lat1, lat2 = math.radians(a['latitude']), math.radians(b['latitude'])
        dlat, dlon = lat2-lat1, math.radians(b['longitude']-a['longitude'])
        angle = 2 * math.asin(min(1, math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2)))
        return 3440.065 * angle

    def profile(self, call, bid, start, strategy='maximum', carry=None):
        b, v = self.berths[bid], self.vessels[call['vessel_id']]
        t = self.terminals[b['terminal_id']]
        pid = t['port_id']
        distance = self.distance(call, bid)
        if distance is None:
            return None
        release = self.release(call) + math.ceil(distance/self.policy.transit_speed_knots*4)
        if not carry and (start < release or start >= TAIL or self.closed[pid][start] or self.berth_closed[bid][start] or not self.compatible(call, bid, start)):
            return None
        remaining = math.ceil(carry['remaining_moves']) if carry else call['unload_moves']+call['load_moves']
        if remaining <= 0:
            return None
        entry = 0 if carry else self.policy.berth_entry_buffer_minutes//15
        total = remaining
        segments, work, shift_counts = [], [], [0]*15
        limit = min(v['max_cranes'], b['max_cranes'])
        safe_stock = max(self.yards[t['id']]['closing_teu'], self.planning_capacity[t['id']])
        rate_factor = weather_factor(self.weather[pid]['wind_mps'], self.weather[pid]['rain_mm_per_hour']) * yard_factor(safe_stock, t['yard_capacity_teu'])
        for i in range(start+entry, TAIL):
            if self.closed[pid][i] or self.berth_closed[bid][i]:
                continue
            live = [c for c in self.home[bid] if self.available[c['id']][i]
                    and (v['required_equipment'] == 'panamax_sts' or c['equipment'] == 'super_post_panamax_sts')]
            if carry:
                # Preserve the observed bundle; any member outage pauses carry work.
                live = [c for c in live if c['id'] in carry['crane_ids']]
                if len(live) != len(carry['crane_ids']):
                    continue
            count = min(len(live), limit)
            if strategy == 'economical':
                count = min(count, max(1, math.ceil(total/1000)))
            elif strategy == 'fcfs':
                count = min(count, 2)
            elif strategy == 'shift_balanced' and (i//SHIFT) % 3 == 2:
                count = max(1, count-1) if count else 0
            if count == 0:
                continue
            bundle = [c['id'] for c in live[:count]]
            rate = sum(self.cranes[c]['productivity_moves_per_hour'] for c in bundle)*count**-.18*rate_factor
            if rate <= 0:
                continue
            moves = min(remaining, rate*.25)
            work.append(i)
            shift_counts[i//SHIFT] = max(shift_counts[i//SHIFT], count)
            if segments and segments[-1]['end_slot'] == i and segments[-1]['crane_ids'] == bundle and segments[-1]['shift_index'] == i//SHIFT:
                segments[-1]['end_slot'] = i+1
                segments[-1]['moves'] += moves
            else:
                segments.append(dict(start_slot=i, end_slot=i+1, crane_ids=bundle, shift_index=i//SHIFT, moves=moves))
            remaining -= moves
            if remaining <= 1e-7:
                completion = i+1
                departure = completion + self.policy.berth_exit_buffer_minutes//15
                while departure < TAIL and (self.closed[pid][departure] or self.berth_closed[bid][departure] or not self.compatible(call, bid, departure)):
                    departure += 1
                if departure > TAIL or (departure == TAIL and (self.closed[pid][-1] or self.berth_closed[bid][-1] or not self.compatible(call, bid, departure))):
                    return None
                return dict(call_id=call['id'], berth_id=bid, start_slot=start, completion_slot=completion,
                    end_slot=departure, waiting_minutes=max(0, start-release)*15, planned_moves=total,
                    crane_ids=sorted({cid for seg in segments for cid in seg['crane_ids']}),
                    execution_profile=dict(segments=segments, productive_slots=work, shift_cranes=shift_counts,
                        strategy=strategy, reroute_distance_nm=distance, release_slot=release, carry=bool(carry),
                        origin=stamp(self.origin), additional_wait_minutes=max(0, start-release)*15,
                        accrued_wait_minutes=0 if carry else self.accrued_wait_minutes(call)))
        return None

    def public(self, option):
        from app.services.forecasting import reason
        return dict(call_id=option['call_id'], berth_id=option['berth_id'], start=stamp(self.times[option['start_slot']]),
            end=stamp(self.times[option['end_slot']]), completion_time=stamp(self.times[option['completion_slot']]),
            waiting_minutes=option['waiting_minutes']+option['execution_profile'].get('accrued_wait_minutes', 0), planned_moves=option['planned_moves'], crane_ids=option['crane_ids'],
            execution_profile=option['execution_profile'], reasons=[reason('EXECUTABLE_RESOURCE_ALLOCATION',
                'Compatible berth, known calendars, shift crane choices and conservative productive capacity',
                shift_cranes=option['execution_profile']['shift_cranes'], strategy=option['execution_profile']['strategy'])])


def staging_moves(resources, option):
    call = resources.calls[option['call_id']]
    carry = next((c for c in resources.data['carry_in'] if c['call_id'] == option['call_id']), None)
    if carry and carry.get('remaining_unload_moves') is not None and carry.get('remaining_load_moves') is not None:
        return carry['remaining_unload_moves']*call['teu_per_move'], carry['remaining_load_moves']*call['teu_per_move']
    fraction = option['planned_moves']/max(1, call['unload_moves']+call['load_moves'])
    return call['unload_moves']*call['teu_per_move']*fraction, call['load_moves']*call['teu_per_move']*fraction


def yard_trace(resources, options, gate_plan=None, only_terminal=None):
    """Conservative staging: all discharge at entry, all loading at completion."""
    traces, gates, valid = [], {}, True
    for tid, t in resources.terminals.items():
        if only_terminal and tid != only_terminal:
            continue
        incoming, outgoing = [0]* (TAIL+1), [0]*(TAIL+1)
        for o in options:
            if resources.berths[o['berth_id']]['terminal_id'] != tid:
                continue
            unload, load = staging_moves(resources, o)
            incoming[o['start_slot']] += math.ceil(unload*TEU_SCALE)
            outgoing[o['completion_slot']] += math.floor(load*TEU_SCALE)
        needed = [0]*(TAIL+2)
        for i in range(TAIL, -1, -1):
            needed[i] = max(0, needed[i+1]+outgoing[i]-incoming[i])
        inventory = math.ceil(resources.yards[tid]['closing_teu']*TEU_SCALE)
        capacity = math.floor(resources.planning_capacity[tid]*TEU_SCALE)
        reserve = min(inventory, math.floor(t['yard_capacity_teu']*.35*TEU_SCALE))
        chosen = []
        for i in range(TAIL+1):
            peak = inventory+incoming[i]
            inventory = peak-outgoing[i]
            if inventory < 0 or peak > capacity:
                valid = False
            factor = min([e['value'] for e in resources.data['disruptions'] if e['kind'] == 'yard_congestion'
                and e.get('terminal_id') == tid and parse(e['start']) <= resources.times[i] < parse(e['end'])] or [1])
            available = math.floor(t['gate_capacity_teu_per_hour']*.25*factor*TEU_SCALE) if i < TAIL else 0
            gate = gate_plan[tid][i] if gate_plan is not None and i < TAIL else min(available, max(0, inventory-max(reserve, needed[i+1])))
            if gate < 0 or gate > available or gate > inventory:
                valid = False
            inventory -= gate
            chosen.append(gate)
            traces.append(dict(terminal_id=tid, timestamp=stamp(resources.times[i]),
                peak_teu=peak/TEU_SCALE, closing_teu=inventory/TEU_SCALE, gate_outbound_teu=gate/TEU_SCALE))
        gates[tid] = chosen[:TAIL]
    return valid, traces, gates
