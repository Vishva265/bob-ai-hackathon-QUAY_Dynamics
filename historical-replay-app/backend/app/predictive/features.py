"""The same as-of feature builder is used offline and against operational DB data.

Scheduled calls are assumed published seven days ahead in this synthetic demo.
Observation fields are gated by their availability time, never by CSV row order.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.synthetic.simulator import compatible, weather_factor, yard_factor
from app.synthetic.schema import SCHEMA

FEATURE_VERSION = 'asof_operational_v2'
LEVELS = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
UNITS = {
    'lead_hours': 'hours', 'berth_count': 'berths', 'yard_capacity_teu': 'TEU',
    'incoming_teu_24h': 'TEU', 'incoming_moves_24h': 'moves',
    'workload_capacity_ratio_24h': 'ratio',
    'workload_backlog_hours_24h': 'hours',
    'mean_vessel_capacity_teu': 'TEU', 'large_vessel_fraction': 'ratio',
    'feeder_fraction': 'ratio', 'panamax_fraction': 'ratio',
    'mean_draft_m': 'm', 'max_draft_m': 'm', 'draft_std_m': 'm',
    'compatible_berth_hours_24h': 'berth-hours', 'current_berth_utilisation': 'ratio',
    'projected_berth_utilisation': 'ratio', 'queue_length': 'vessels',
    'yard_occupancy_pct': '%', 'dwell_proxy_hours': 'hours',
    'dwell_proxy_trend_hours': 'hours', 'available_crane_hours_24h': 'crane-hours',
    'rolling_crane_productivity': 'moves/crane-hour', 'maintenance_flag': 'boolean',
    'breakdown_flag': 'boolean', 'wind_mps': 'm/s', 'visibility_m': 'm',
    'tide_height_m': 'm', 'wind_risk': 'boolean', 'visibility_risk': 'boolean',
    'tide_risk_fraction': 'ratio', 'weather_age_hours': 'hours',
    'yard_age_hours': 'hours', 'tide_missing': 'boolean',
    'waiting_avg_24h': 'hours', 'waiting_avg_7d': 'hours',
    'eta_deviation_mean_hours': 'hours', 'eta_uncertainty_std_hours': 'hours',
    'hour_sin': 'ratio', 'hour_cos': 'ratio', 'weekday': '0..6',
    'holiday_indicator': 'boolean', 'holiday_calendar_missing': 'boolean',
    'call_moves': 'moves', 'call_teu': 'TEU', 'call_draft_m': 'm',
    'call_capacity_teu': 'TEU', 'call_priority': 'rank 1..5',
    'call_compatible_berths': 'berths', 'call_service_hours': 'hours',
    'historical_wait_missing': 'boolean', 'productivity_missing': 'boolean',
}
UNITS.update({f'arrivals_next_{h}h': 'vessels' for h in (3, 6, 12, 24)})
UNITS.update({f'rolling_level_{i}': 'probability' for i in range(4)})
FEATURES = list(UNITS)


def level(queue, occupancy, utilisation):
    """Predeclared operational severity; not tuned to evaluation scores."""
    if queue >= 4 or occupancy >= .95:
        return 3
    if queue >= 2 or occupancy >= .85 or utilisation >= .95:
        return 2
    if queue > 0 or occupancy >= .65 or utilisation >= .75:
        return 1
    return 0


def frame(rows, times=(), columns=None):
    result = pd.DataFrame(rows, columns=columns)
    for key in times:
        if key in result:
            result[key] = pd.to_datetime(result[key], utc=True)
    return result


def mean(values, default=0):
    return float(np.mean(values)) if len(values) else float(default)


class FeatureBuilder:
    def __init__(self, tables, holidays=None, observation_cutoff=None):
        self.tables = tables
        self.holidays = holidays  # port_id -> ISO local dates; None explicitly missing
        self.terminals = {r['id']: r for r in tables['terminals']}
        self.ports = {r['id']: r for r in tables['ports']}
        self.berths = {r['id']: r for r in tables['berths']}
        self.cranes = {r['id']: r for r in tables['cranes']}
        self.vessels = {r['id']: r for r in tables['vessels']}
        self.calls = frame(tables['vessel_calls'], ['scheduled_eta'], columns=list(SCHEMA['vessel_calls']))
        self.calls['port_id'] = self.calls.terminal_id.map(lambda t: self.terminals[t]['port_id'])
        self.call_map = {r['id']: r for r in self.calls.to_dict('records')}
        outcomes = tables.get('call_outcomes', [])
        self.outcomes = frame(outcomes, ['actual_arrival', 'berth_start', 'departure'])
        self.observation_cutoff = pd.Timestamp(observation_cutoff) if observation_cutoff else None
        if 'vessel_call_observations' in tables:
            events = tables['vessel_call_observations']
        else:
            events = [dict(call_id=o['call_id'], kind=kind, timestamp=o[field], berth_id=o['berth_id'] if kind != 'arrival' else None)
                      for o in outcomes for kind, field in [('arrival', 'actual_arrival'), ('berth_start', 'berth_start'), ('departure', 'departure')]]
        self.events = frame(events, ['timestamp'])
        if self.observation_cutoff and len(self.events):
            self.events = self.events[(self.events.timestamp < self.observation_cutoff) |
                ((self.events.kind == 'departure') & (self.events.timestamp == self.observation_cutoff))]
        if len(self.outcomes):
            self.outcomes['terminal_id'] = self.outcomes.call_id.map(lambda c: self.call_map[c]['terminal_id'])
        self.yards = frame(tables.get('yard_snapshots', []), ['timestamp'])
        if len(self.yards):
            reconciliation={r['snapshot_id']:pd.Timestamp(r['known_at']) for r in tables.get('yard_reconciliations',[])}
            self.yards['known_at']=[reconciliation.get(r.id,r.timestamp+pd.Timedelta(hours=1)) for r in self.yards.itertuples()]
            self.yards['instant_observation']=self.yards.id.isin(reconciliation)
        self.weather = frame(tables.get('weather', []), ['timestamp'])
        if len(self.weather) and 'period' in self.weather:
            self.weather = self.weather[self.weather.period == 'historical_observation']
        self.tides = frame(tables.get('tides', []), ['timestamp'])
        if self.observation_cutoff and len(self.tides):
            self.tides = self.tides[self.tides.timestamp < self.observation_cutoff]
        self.handling = frame(tables.get('handling_log', []), ['timestamp'])
        if len(self.handling):
            self.handling['terminal_id'] = self.handling.call_id.map(lambda c: self.call_map[c]['terminal_id'])
        self.availability = frame(tables.get('crane_availability', []), ['start', 'end'])
        self.cargo = {(r['berth_id'], r['cargo_type']) for r in tables['berth_cargo_compatibility']}
        self._cache = {}
        self._history_cache = {}
        self._event_intervals = {}
        departure = {r.call_id: r.timestamp.value for r in self.events[self.events.kind == 'departure'].itertuples()} if len(self.events) else {}
        for bid in self.berths:
            entries = self.events[(self.events.kind == 'berth_start') & (self.events.berth_id == bid)] if len(self.events) else self.events
            self._event_intervals[bid] = (np.array([r.timestamp.value for r in entries.itertuples()], dtype=np.int64),
                np.array([departure.get(r.call_id, np.iinfo(np.int64).max) for r in entries.itertuples()], dtype=np.int64))

    def scope(self, terminal_id=None, port_id=None):
        return [terminal_id] if terminal_id else sorted(t for t, r in self.terminals.items() if r['port_id'] == port_id)

    def utilisation(self, tids, timestamp):
        bids = {b for b, r in self.berths.items() if r['terminal_id'] in tids}
        # Membership tests implement observed entry/release events; unseen event values never enter features.
        ns = pd.Timestamp(timestamp).value
        occupied = {bid for bid in bids if np.any((self._event_intervals[bid][0] <= ns) & (self._event_intervals[bid][1] > ns))}
        occupied.update(c['berth_id'] for c in self.tables.get('carry_in_operations', [])
                        if c['berth_id'] in bids and pd.Timestamp(c['known_at']) <= timestamp)
        return len(occupied)/max(1, len(bids))

    def observed_visits(self, tids, origin):
        events = self.events[self.events.timestamp <= origin] if len(self.events) else self.events
        if not len(events):
            return self.outcomes.iloc[:0]
        arrivals = events[events.kind == 'arrival'][['call_id', 'timestamp']].rename(columns={'timestamp': 'actual_arrival'})
        entries = events[events.kind == 'berth_start'][['call_id', 'timestamp']].rename(columns={'timestamp': 'berth_start'})
        result = arrivals.merge(entries, on='call_id', how='left')
        result['terminal_id'] = result.call_id.map(lambda c: self.call_map[c]['terminal_id'])
        return result[result.terminal_id.isin(tids)]

    def level_history(self, tids):
        key = tuple(sorted(tids))
        if key in self._history_cache:
            return self._history_cache[key]
        grouped = self.yards[self.yards.terminal_id.isin(tids) & ~self.yards.instant_observation].groupby('timestamp').agg(
            queue=('queued_vessels', 'sum'), stock=('closing_teu', 'sum'), count=('terminal_id', 'count'))
        grouped = grouped[grouped['count'] == len(tids)]
        capacity = sum(self.terminals[t]['yard_capacity_teu'] for t in tids)
        ticks = np.array([ts.value for ts in grouped.index], dtype=np.int64)
        occupied = np.zeros(len(ticks))
        bids = [b for b, r in self.berths.items() if r['terminal_id'] in tids]
        for bid in bids:
            start, end = self._event_intervals[bid]
            if len(start):
                occupied += ((start[None, :] <= ticks[:, None]) & (end[None, :] > ticks[:, None])).any(axis=1)
        queue, stock, utilisation = grouped.queue.to_numpy(), grouped.stock.to_numpy()/capacity, occupied/max(1, len(bids))
        labels = np.select([(queue >= 4) | (stock >= .95), (queue >= 2) | (stock >= .85) | (utilisation >= .95),
                            (queue > 0) | (stock >= .65) | (utilisation >= .75)], [3, 2, 1], default=0)
        result = pd.Series(labels, index=grouped.index)
        self._history_cache[key] = result
        return result

    def historical_levels(self, tids, origin):
        all_levels = self.level_history(tids)
        history = all_levels[(all_levels.index+pd.Timedelta(hours=1) <= origin) & (all_levels.index >= origin-timedelta(days=7))]
        counts = np.bincount(history.to_numpy(), minlength=4).astype(float)
        return counts/counts.sum() if counts.sum() else np.array([1., 0., 0., 0.])

    def context(self, origin, terminal_id=None, port_id=None):
        origin = pd.Timestamp(origin)
        if self.observation_cutoff and origin > self.observation_cutoff:
            raise ValueError('as_of cannot exceed the available simulator observation cutoff')
        key = (origin, terminal_id, port_id)
        if key in self._cache:
            return self._cache[key]
        tids = self.scope(terminal_id, port_id)
        pid = self.terminals[tids[0]]['port_id']
        berths = [r for r in self.berths.values() if r['terminal_id'] in tids]
        cranes = [r for r in self.cranes.values() if self.berths[r['berth_id']]['terminal_id'] in tids]
        latest_yards = self.yards[self.yards.terminal_id.isin(tids) &
            (self.yards.known_at <= origin) & (self.yards.timestamp<=origin)].sort_values('timestamp').groupby('terminal_id').tail(1)
        if len(latest_yards) != len(tids):
            raise ValueError('Complete as-of yard observations are required')
        w = self.weather[(self.weather.port_id == pid) & (self.weather.timestamp <= origin)].sort_values('timestamp')
        if not len(w):
            raise ValueError('An as-of weather observation is required')
        w = w.iloc[-1]
        tide = self.tides[(self.tides.port_id == pid) & (self.tides.timestamp <= origin)] if len(self.tides) else self.tides
        tide_value = float(tide.sort_values('timestamp').iloc[-1].height_m) if len(tide) else -1.3
        capacity = sum(self.terminals[t]['yard_capacity_teu'] for t in tids)
        stock = float(latest_yards.closing_teu.sum())
        history = self.yards[self.yards.terminal_id.isin(tids) &
            (self.yards.known_at <= origin) & ~self.yards.instant_observation & (self.yards.timestamp >= origin-timedelta(days=2))]
        # Aggregate inventory/outflow residence proxy; actual container dwell events do not exist.
        dwell = []
        for low, high in ((origin-timedelta(days=2), origin-timedelta(days=1)), (origin-timedelta(days=1), origin)):
            part = history[(history.timestamp >= low) & (history.timestamp < high)]
            hourly = part.groupby('timestamp').agg(stock=('closing_teu', 'sum'), gate=('gate_outbound_teu', 'sum'), ship=('outbound_teu', 'sum'))
            outflow = float((hourly.gate+hourly.ship).mean()) if len(hourly) else 0
            dwell.append(float(hourly.stock.mean())/max(1., outflow) if len(hourly) else 0.)
        observed = self.observed_visits(tids, origin)
        observed_time = min(origin, self.observation_cutoff-pd.Timedelta(microseconds=1)) if self.observation_cutoff else origin
        waits = observed[(observed.berth_start <= observed_time) & (observed.berth_start > origin-timedelta(days=7))] if len(observed) else observed
        waits24 = waits[waits.berth_start > origin-timedelta(hours=24)] if len(waits) else waits
        # waiting_hours itself is never consulted; derive from already observed entry/arrival events.
        wait_values = (waits.berth_start-waits.actual_arrival).dt.total_seconds()/3600 if len(waits) else []
        wait24 = (waits24.berth_start-waits24.actual_arrival).dt.total_seconds()/3600 if len(waits24) else []
        arrivals = observed[(observed.actual_arrival <= observed_time) & (observed.actual_arrival > origin-timedelta(days=7))] if len(observed) else observed
        deviations = [(r.actual_arrival-self.call_map[r.call_id]['scheduled_eta']).total_seconds()/3600 for r in arrivals.itertuples()] if len(arrivals) else []
        handling = self.handling[self.handling.terminal_id.isin(tids) &
            (self.handling.timestamp+pd.Timedelta(hours=1) <= origin) &
            (self.handling.timestamp > origin-timedelta(days=7))] if len(self.handling) else self.handling
        crane_hours = float((handling.active_cranes*handling.productive_fraction).sum()) if len(handling) else 0
        productivity = float(handling.handled_moves.sum())/crane_hours if crane_hours else mean([c['productivity_moves_per_hour'] for c in cranes])
        known = self.availability[self.availability.crane_id.isin([c['id'] for c in cranes]) &
            ((self.availability.reason == 'maintenance') | (self.availability.start <= observed_time))] if len(self.availability) else self.availability
        # Ongoing breakdown recovery is unknown: persist failure through projection.
        slots = np.zeros((len(cranes), 192), dtype=bool)
        slot_starts = origin.value+np.arange(192, dtype=np.int64)*3_600_000_000_000
        slot_ends = slot_starts+3_600_000_000_000
        crane_indices = {c['id']: i for i, c in enumerate(cranes)}
        for a in known.itertuples() if len(known) else []:
            end = origin.value+168*3_600_000_000_000 if a.reason != 'maintenance' and a.end > origin else a.end.value
            slots[crane_indices[a.crane_id]] |= (a.start.value < slot_ends) & (end > slot_starts)
        levels = self.historical_levels(tids, origin)
        values = dict(berth_count=len(berths), yard_capacity_teu=capacity,
            current_berth_utilisation=self.utilisation(tids, origin), queue_length=float(latest_yards.queued_vessels.sum()),
            yard_occupancy_pct=100*stock/capacity, dwell_proxy_hours=dwell[1], dwell_proxy_trend_hours=dwell[1]-dwell[0],
            available_crane_hours_24h=float((~slots[:, :24]).sum()), rolling_crane_productivity=productivity,
            maintenance_flag=int(len(known[(known.reason == 'maintenance') & (known.start < origin+timedelta(hours=72)) & (known.end > origin)]) > 0) if len(known) else 0,
            breakdown_flag=int(len(known[(known.reason != 'maintenance') & (known.start <= origin) & (known.end > origin)]) > 0) if len(known) else 0,
            wind_mps=float(w.wind_mps), visibility_m=float(w.visibility_m), wind_risk=int(w.wind_mps >= 10), visibility_risk=int(w.visibility_m < 500),
            tide_height_m=tide_value, tide_missing=int(not len(tide)),
            weather_age_hours=(origin-w.timestamp).total_seconds()/3600,
            yard_age_hours=max((origin-ts).total_seconds()/3600 for ts in latest_yards.known_at),
            waiting_avg_7d=mean(wait_values), waiting_avg_24h=mean(wait24, mean(wait_values)),
            eta_deviation_mean_hours=mean(deviations), eta_uncertainty_std_hours=float(np.std(deviations)) if deviations else 0.,
            historical_wait_missing=int(not len(wait_values)), productivity_missing=int(not crane_hours),
            **{f'rolling_level_{i}': float(p) for i, p in enumerate(levels)})
        total_rate = sum(sum(c['productivity_moves_per_hour'] for c in cranes if c['berth_id'] == b['id'])*
                         sum(c['berth_id'] == b['id'] for c in cranes)**-.18 for b in berths)*weather_factor(float(w.wind_mps), float(w.rain_mm_per_hour))*yard_factor(stock, capacity)
        berth_up = {b['id']: (~slots[[i for i, c in enumerate(cranes) if c['berth_id'] == b['id']]]).any(axis=0) for b in berths}
        context = dict(values=values, tids=tids, pid=pid, berths=berths, cranes=cranes, tide=tide_value,
                       rate=max(1., total_rate), origin=origin, known=known, berth_up=berth_up, crane_up=~slots)
        self._cache[key] = context
        return context

    def row(self, origin, bucket, terminal_id=None, port_id=None, call=None):
        origin, bucket = pd.Timestamp(origin), pd.Timestamp(bucket)
        ctx = self.context(origin, terminal_id, port_id)
        values = dict(ctx['values'])
        # Only the seven-day published schedule is visible; no future actual arrivals.
        scheduled = self.calls[self.calls.terminal_id.isin(ctx['tids']) &
            (self.calls.scheduled_eta >= origin) & (self.calls.scheduled_eta < origin+timedelta(days=7))]
        for h in (3, 6, 12, 24):
            values[f'arrivals_next_{h}h'] = int(((scheduled.scheduled_eta >= bucket) & (scheduled.scheduled_eta < bucket+timedelta(hours=h))).sum())
        incoming = scheduled[(scheduled.scheduled_eta >= bucket) & (scheduled.scheduled_eta < bucket+timedelta(hours=24))]
        ships = [self.vessels[r.vessel_id] for r in incoming.itertuples()]
        values.update(incoming_teu_24h=float(((incoming.unload_moves+incoming.load_moves)*incoming.teu_per_move).sum()),
            incoming_moves_24h=float((incoming.unload_moves+incoming.load_moves).sum()),
            mean_vessel_capacity_teu=mean([v['capacity_teu'] for v in ships]), large_vessel_fraction=mean([v['size_class'] == 'ultra_large' for v in ships]),
            feeder_fraction=mean([v['size_class'] == 'feeder' for v in ships]), panamax_fraction=mean([v['size_class'] == 'panamax' for v in ships]),
            mean_draft_m=mean([v['draft_m'] for v in ships]), max_draft_m=max([v['draft_m'] for v in ships], default=0),
            draft_std_m=float(np.std([v['draft_m'] for v in ships])) if ships else 0)
        candidates, tide_risks = set(), []
        for c in incoming.to_dict('records'):
            vessel = self.vessels[c['vessel_id']]
            conservative = [b for b in ctx['berths'] if compatible(vessel, c, b, self.cargo, -1.3)]
            live = [b for b in ctx['berths'] if compatible(vessel, c, b, self.cargo, ctx['tide'])]
            candidates.update(b['id'] for b in conservative)
            tide_risks.append(len(conservative) < len(live) or not live)
        if not len(incoming):
            candidates.update(b['id'] for b in ctx['berths'])
        # Compatible berth-hours account for planned complete crane shutdowns, not realised future work.
        berth_hours = 0.
        offset = max(0, int((bucket-origin).total_seconds()/3600))
        for bid in candidates:
            berth_hours += float(ctx['berth_up'][bid][offset:offset+24].sum())
        available_crane_hours = float(ctx['crane_up'][:, offset:offset+24].sum())
        handling_capacity = max(1., available_crane_hours*values['rolling_crane_productivity'])
        workload_ratio = values['incoming_moves_24h']/handling_capacity
        # An explicit capacity-pressure interaction lets simple models
        # extrapolate into arrival surges instead of treating raw workload and
        # crane availability as unrelated linear inputs.
        backlog_hours = max(0., values['incoming_moves_24h']/(handling_capacity/24)-24)
        values.update(compatible_berth_hours_24h=berth_hours,
            available_crane_hours_24h=available_crane_hours,
            workload_capacity_ratio_24h=workload_ratio,
            workload_backlog_hours_24h=backlog_hours,
            tide_risk_fraction=mean(tide_risks),
            projected_berth_utilisation=min(4., values['incoming_moves_24h']/ctx['rate']/24+
                values['current_berth_utilisation']*max(0, 1-(bucket-origin).total_seconds()/3600/24)))
        local = bucket.to_pydatetime().astimezone(ZoneInfo(self.ports[ctx['pid']]['timezone']))
        calendar = self.holidays or {}
        values.update(lead_hours=(bucket-origin).total_seconds()/3600, hour_sin=np.sin(2*np.pi*local.hour/24),
            hour_cos=np.cos(2*np.pi*local.hour/24), weekday=local.weekday(),
            holiday_indicator=int(local.date().isoformat() in calendar.get(ctx['pid'], [])),
            holiday_calendar_missing=int(ctx['pid'] not in calendar))
        values.update(call_moves=0., call_teu=0., call_draft_m=0., call_capacity_teu=0., call_priority=3., call_compatible_berths=0., call_service_hours=0.)
        if call:
            vessel = self.vessels[call['vessel_id']]
            choices = [b for b in ctx['berths'] if compatible(vessel, call, b, self.cargo, -1.3)]
            rates = []
            for b in choices:
                home = sorted([c['productivity_moves_per_hour'] for c in ctx['cranes'] if c['berth_id'] == b['id']], reverse=True)
                n = min(len(home), vessel['max_cranes'], b['max_cranes'])
                rates.append(sum(home[:n])*n**-.18*weather_factor(values['wind_mps'], 0)*yard_factor(values['yard_occupancy_pct']/100, 1))
            moves = call['unload_moves']+call['load_moves']
            values.update(call_moves=moves, call_teu=moves*call['teu_per_move'], call_draft_m=vessel['draft_m'],
                call_capacity_teu=vessel['capacity_teu'], call_priority=call['priority'], call_compatible_berths=len(choices), call_service_hours=moves/max(1., max(rates, default=1.)))
        return {key: float(values[key]) for key in FEATURES}

    def target_level(self, bucket, terminal_id=None, port_id=None):
        tids = self.scope(terminal_id, port_id)
        history = self.level_history(tids)
        return int(history.loc[bucket]) if bucket in history.index else None
