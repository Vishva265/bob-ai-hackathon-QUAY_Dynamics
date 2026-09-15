"""Persisted ML-backed early warning use case; no HTTP or generative AI logic."""
from datetime import timedelta
from uuid import uuid4
import json

from sqlalchemy import select
from pydantic import ValidationError

from app import models as m
from app.errors import DomainError
from app.early_warning.rules import AlertRules
from app.early_warning.projection import project
from app.repositories.alerts import AlertRepository
from app.repositories.operations import Repository
from app.services.context import apply_overrides
from app.services.operations import record
from app.synthetic.simulator import parse

ASSUMPTIONS = [
    'Continuous operational metrics use a deterministic 15-minute FIFO resource projection; they are not calibrated ML outputs or an optimised plan.',
    'Port/terminal probabilities come from the trained model. Berths inherit their terminal probability prior and always require low-confidence review.',
    'Probability bands are model event-error bands, not confidence intervals for the probability. Confidence levels are configurable operator attention categories.',
    'Latest known weather persists; published maintenance is known, active breakdowns persist without assuming actual future repair times.',
    'Observed mean gate-out throughput over the last 24 fully observed hours persists. Yard exchange follows call unload/load proportions and respects physical stock bounds.',
    'Conservative tide (-1.3 m) screening applies to new berth placements; observed in-progress placements remain fixed. Cranes remain at their home berth.',
    'Published ETA is the assumed arrival for unobserved vessels; ML waiting predictions inform average queue wait without shifting ETA or overriding resource constraints.',
    'Queue length is a quarter-hour average; berth queues fractionally attribute waiting vessels across compatible berths and sum to terminal queues.',
    'The first hotspot duration covers its contiguous episode; all episodes and total hours are retained. Episodes reaching hour 72 are horizon-censored.',
    'Alert deduplication uses one active entity/rule episode. A clear complete scoped forecast resolves it; recurrence opens a new episode. Acknowledgement persists across refreshes.',
]


class EarlyWarningService:
    def __init__(self, session):
        self.session, self.repo, self.alerts = session, Repository(session), AlertRepository(session)

    def rules(self):
        try:
            return AlertRules.configured()
        except (OSError, ValueError, ValidationError) as exc:
            raise DomainError('INVALID_ALERT_CONFIGURATION', str(exc), 503) from exc

    def run(self, payload):
        from app.services.forecasting import ForecastService
        rules = payload.rules if payload.rules is not None else self.rules()
        return ForecastService(self.session).run(payload, early_warning_rules=rules)

    def enrich(self, run, snapshot, rules):
        if not run.model_version:
            raise DomainError('MODEL_UNAVAILABLE', 'Early warning requires a trained model; train or configure MODEL_DIRECTORY', 503)
        origin = parse(snapshot["as_of"])
        data = apply_overrides(snapshot)
        if any(not any(b['terminal_id'] == t['id'] for b in data['berths']) for t in data['terminals']) or any(
                not any(t['port_id'] == pid for t in data['terminals']) for pid in data['port_ids']):
            raise DomainError('MISSING_RESOURCES', 'Every selected port and terminal needs berth inventory for complete early warning', 503)
        scopes = {('port', pid) for pid in data['port_ids']} | {('terminal', t['id']) for t in data['terminals']} | {('berth', b['id']) for b in data['berths']}
        self.alerts.lock_scopes(scopes, origin)
        predictions = {(p.scope, p.scope_id, parse(p.timestamp)): record(p) for p in run.predictive_buckets}
        waiting = {p.call_id: record(p) for p in run.waiting_predictions}
        observations = [record(o) for o in self.session.scalars(select(m.VesselCallObservation).where(m.VesselCallObservation.timestamp <= origin))]
        yard_table = m.source_tables['yard_snapshots']
        history = list(self.session.execute(select(yard_table).where(yard_table.c.timestamp >= origin - timedelta(hours=24),
            yard_table.c.timestamp <= origin - timedelta(hours=1))).mappings())
        gate_rates = {t['id']: sum(y['gate_outbound_teu'] for y in history if y['terminal_id'] == t['id']) /
                      max(1, sum(y['terminal_id'] == t['id'] for y in history)) for t in data['terminals']}
        rows, summaries = project(data, predictions, waiting, observations, gate_rates, rules, origin)
        warning_run = m.EarlyWarningRun(id=run.id, rules=rules.model_dump(), projection_method='fifo_quarter_hour_v1',
            summaries=json.loads(json.dumps(summaries, default=lambda v: v.isoformat())), alert_counts={}, assumptions=ASSUMPTIONS)
        self.session.add(warning_run)
        self.session.flush()
        fields = {c.name for c in m.OperationalForecast.__table__.columns} - {'id', 'run_id'}
        self.session.add_all([m.OperationalForecast(id=str(uuid4()), run_id=run.id, **{k: row[k] for k in fields}) for row in rows])
        warning_run.alert_counts = self.alerts.reconcile(run.id, rows, scopes)
        self.session.flush()
        return warning_run

    def output(self, run_id):
        run = self.repo.get(m.ForecastRun, run_id)
        warning = self.repo.get(m.EarlyWarningRun, run_id)
        from app.services.forecasting import ForecastService
        result = ForecastService(self.session).output(run)
        result.update(operational_bucket_count=self.session.query(m.OperationalForecast).filter_by(run_id=run_id).count(),
                      projection_method=warning.projection_method, rules=warning.rules, summaries=warning.summaries,
                      alert_counts=warning.alert_counts, assumptions=warning.assumptions)
        return result

    def buckets(self, limit, cursor, run_id=None, port_id=None, terminal_id=None, berth_id=None, scope=None, start=None, end=None, hotspots_only=False):
        conditions = []
        for field, value, model in [('run_id', run_id, m.EarlyWarningRun), ('port_id', port_id, m.Port),
                                    ('terminal_id', terminal_id, m.Terminal), ('berth_id', berth_id, m.Berth)]:
            if value:
                self.repo.get(model, value)
                conditions.append(getattr(m.OperationalForecast, field) == value)
        if scope:
            conditions.append(m.OperationalForecast.scope == scope)
        if start and end and start >= end:
            raise DomainError('INVALID_WINDOW', 'end must follow start')
        if start:
            conditions.append(m.OperationalForecast.timestamp >= start)
        if end:
            conditions.append(m.OperationalForecast.timestamp < end)
        if hotspots_only:
            conditions.append(m.OperationalForecast.is_hotspot == 1)
        context = dict(run_id=run_id, port_id=port_id, terminal_id=terminal_id, berth_id=berth_id, scope=scope, start=start, end=end, hotspots_only=hotspots_only)
        return self.repo.page(m.OperationalForecast, conditions, limit, cursor, context)

    def list_alerts(self, limit, cursor, port_id=None, scope=None, scope_id=None, state=None, rule_code=None):
        if port_id:
            self.repo.get(m.Port, port_id)
        values = dict(port_id=port_id, scope=scope, scope_id=scope_id, state=state, rule_code=rule_code)
        return self.repo.page(m.CongestionAlert, [getattr(m.CongestionAlert, k) == v for k, v in values.items() if v is not None], limit, cursor, values)

    def acknowledge(self, alert_id, payload):
        return self.alerts.acknowledge(self.repo.get(m.CongestionAlert, alert_id), payload.actor, payload.expected_revision)

    def events(self, alert_id, limit, cursor):
        self.repo.get(m.CongestionAlert, alert_id)
        return self.repo.page(m.AlertEvent, [m.AlertEvent.alert_id == alert_id], limit, cursor, dict(alert_id=alert_id))
