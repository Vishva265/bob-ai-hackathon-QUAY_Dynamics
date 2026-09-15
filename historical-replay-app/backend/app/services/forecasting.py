"""Berth-capacity baseline and optional versioned predictive enrichment."""
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app import models as m
from app.errors import DomainError
from app.repositories.operations import Repository
from app.services.context import snapshot_inputs, fingerprint, apply_overrides
from app.synthetic.simulator import compatible, parse, stamp, weather_factor, yard_factor


def reason(code, message, **evidence):
    return dict(code=code, message=message, evidence=evidence)


def capacity_inputs(data):
    terminals = {t['id']: t for t in data['terminals']}
    weather = {w['port_id']: w for w in data['weather']}
    yards = {y['terminal_id']: y for y in data['yards']}
    return terminals, weather, yards


class ForecastService:
    def __init__(self, session):
        self.session, self.repo = session, Repository(session)

    def run(self, payload, overrides=None, early_warning_rules=None):
        snapshot = snapshot_inputs(self.session, payload.as_of, payload.port_ids, overrides)
        data = apply_overrides(snapshot)
        terminals, weather, yards = capacity_inputs(data)
        vessels = {v['id']: v for v in data['vessels']}
        cargo = {(c['berth_id'], c['cargo_type']) for c in data['cargo']}
        run = self.repo.add(m.ForecastRun(id=str(uuid4()), as_of=payload.as_of, horizon_hours=72,
            method='scheduled_demand_capacity_v1', quality='heuristic_uncalibrated',
            created_at=datetime.now(timezone.utc), input_hash=fingerprint(snapshot)))
        demand = {(b['id'], h): 0.0 for b in data['berths'] for h in range(72)}
        committed = {a['call_id'] for a in data['commitments']}
        carried = {a['call_id'] for a in data['carry_in']}
        for call in data['calls']:
            if call['id'] in committed | carried:
                continue
            candidates = [b for b in data['berths'] if compatible(vessels[call['vessel_id']], call, b, cargo, -1.3)]
            release = max(0, math.floor((parse(call['scheduled_eta'])-payload.as_of).total_seconds()/3600))
            if not candidates or release >= 72:
                continue
            moves = call['unload_moves']+call['load_moves']
            rates = []
            for b in candidates:
                t = terminals[b['terminal_id']]
                w = weather[t['port_id']]
                home = sorted([c['productivity_moves_per_hour'] for c in data['cranes'] if c['berth_id'] == b['id']], reverse=True)
                count = min(len(home), vessels[call['vessel_id']]['max_cranes'], b['max_cranes'])
                rates.append(sum(home[:count])*count**-.18*weather_factor(w['wind_mps'], w['rain_mm_per_hour'])*yard_factor(yards[t['id']]['closing_teu'], t['yard_capacity_teu']))
            duration = max(1, math.ceil(moves/max(1, max(rates))))
            for b in candidates:
                for h in range(release, min(72, release+duration)):
                    demand[(b['id'], h)] += moves/duration/len(candidates)
        for carry in data['carry_in']:
            if carry['call_id'] in committed:
                continue
            b = next(b for b in data['berths'] if b['id'] == carry['berth_id'])
            t = terminals[b['terminal_id']]
            w = weather[t['port_id']]
            bundle = [c for c in data['cranes'] if c['id'] in carry['crane_ids']]
            rate = sum(c['productivity_moves_per_hour'] for c in bundle)*len(bundle)**-.18*weather_factor(w['wind_mps'], w['rain_mm_per_hour'])*yard_factor(yards[t['id']]['closing_teu'], t['yard_capacity_teu'])
            hours = max(1, math.ceil(carry['remaining_moves']/max(1, rate)))
            for h in range(min(72, hours)):
                demand[(carry['berth_id'], h)] += carry['remaining_moves']/hours
        for assignment in data['commitments']:
            for h in range(72):
                ts = stamp(payload.as_of+timedelta(hours=h))
                if assignment['start'] <= ts < assignment['end']:
                    hours = (parse(assignment['end'])-parse(assignment['start'])).total_seconds()/3600
                    demand[(assignment['berth_id'], h)] += assignment['planned_moves']/hours
        for b in data['berths']:
            terminal = terminals[b['terminal_id']]
            pid = terminal['port_id']
            w = weather[pid]
            yf = yard_factor(yards[b['terminal_id']]['closing_teu'], terminal['yard_capacity_teu'])
            for h in range(72):
                ts = stamp(payload.as_of+timedelta(hours=h))
                down = {a['crane_id'] for a in data['availability'] if a['start'] <= ts < a['end']}
                live = [c for c in data['cranes'] if c['berth_id'] == b['id'] and c['id'] not in down]
                capacity = sum(c['productivity_moves_per_hour'] for c in live)*(len(live)**-.18 if live else 0)*weather_factor(w['wind_mps'], w['rain_mm_per_hour'])*yf
                closed = any(e['kind'] == 'storm' and e['port_id'] == pid and e['start'] <= ts < e['end'] for e in data['disruptions']) or any(
                    c['berth_id'] == b['id'] and parse(c['start']) < payload.as_of+timedelta(hours=h+1) and parse(c['end']) > parse(ts)
                    for c in data.get('berth_closures', []))
                if closed:
                    capacity = 0
                d = demand[(b['id'], h)]
                pressure = d/capacity if capacity > 0 else None
                reasons = [reason('DEMAND_CAPACITY', 'Published handling demand compared with available crane capacity',
                    demand_moves=d, capacity_moves=capacity, yard_factor=yf, observation_time=w['timestamp'])]
                if down:
                    reasons.append(reason('CRANE_UNAVAILABLE', 'Known downtime reduces capacity', crane_ids=sorted(c['id'] for c in data['cranes'] if c['berth_id'] == b['id'] and c['id'] in down)))
                if closed:
                    reasons.append(reason('STORM_CLOSURE', 'Scenario or known storm closes handling', port_id=pid))
                self.session.add(m.CongestionForecast(id=str(uuid4()), run_id=run.id, port_id=pid, berth_id=b['id'],
                    timestamp=ts, demand_moves=d, capacity_moves=capacity, pressure_ratio=pressure,
                    alert=int((pressure is not None and pressure >= .85) or (capacity == 0 and d > 0)), reasons=reasons))
        from app.services.prediction import PredictionService
        prediction_service = PredictionService(self.session)
        predictor = getattr(payload, 'predictor', 'auto')
        if predictor == 'ml' or (predictor == 'auto' and prediction_service.registry.exists()):
            prediction_service.enrich(run, snapshot)
        if early_warning_rules is not None:
            from app.services.early_warning import EarlyWarningService
            EarlyWarningService(self.session).enrich(run, snapshot, early_warning_rules)
        self.session.flush()
        return run

    def output(self, run):
        return dict(id=run.id, as_of=run.as_of, horizon_hours=run.horizon_hours, method=run.method,
            quality=run.quality, created_at=run.created_at, input_hash=run.input_hash, bucket_count=len(run.buckets),
            model_version=run.model_version, predictive_bucket_count=len(run.predictive_buckets), waiting_prediction_count=len(run.waiting_predictions))

    def list(self, limit, cursor, run_id=None, port_id=None, berth_id=None, start=None, end=None):
        conditions = []
        if run_id:
            self.repo.get(m.ForecastRun, run_id)
            conditions.append(m.CongestionForecast.run_id == run_id)
        if port_id:
            self.repo.get(m.Port, port_id)
            conditions.append(m.CongestionForecast.port_id == port_id)
        if berth_id:
            self.repo.get(m.Berth, berth_id)
            conditions.append(m.CongestionForecast.berth_id == berth_id)
        if start and end and end <= start:
            raise DomainError('INVALID_WINDOW', 'end must follow start')
        if start:
            conditions.append(m.CongestionForecast.timestamp >= start)
        if end:
            conditions.append(m.CongestionForecast.timestamp < end)
        return self.repo.page(m.CongestionForecast, conditions, limit, cursor,
            dict(entity='forecasts', run_id=run_id, port_id=port_id, berth_id=berth_id, start=start, end=end))
