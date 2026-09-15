"""Atomic scoped reconciliation and alert state transitions."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app import models as m
from app.errors import DomainError


def scope_key(scope, scope_id):
    return f'{scope}:{scope_id}'


class AlertRepository:
    def __init__(self, session):
        self.session = session

    def lock_scopes(self, scopes, as_of):
        # Unique upsert + UPDATE locks serialize overlapping runs in PostgreSQL;
        # SQLite's write transaction provides the same ordering for the demo.
        if self.session.bind.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        for scope, scope_id in sorted(scopes):
            key = scope_key(scope, scope_id)
            self.session.execute(insert(m.AlertWatermark).values(id=key, as_of=as_of, revision=0).on_conflict_do_nothing(index_elements=['id']))
            changed = self.session.execute(update(m.AlertWatermark).where(m.AlertWatermark.id == key, m.AlertWatermark.as_of <= as_of)
                .values(as_of=as_of, revision=m.AlertWatermark.revision + 1))
            if changed.rowcount != 1:
                raise DomainError('STALE_FORECAST', 'A newer forecast has already reconciled alerts for this entity', 409)

    def event(self, alert, run_id, action, actor=None):
        self.session.add(m.AlertEvent(id=str(uuid4()), alert_id=alert.id, run_id=run_id, action=action,
            actor=actor, occurred_at=datetime.now(timezone.utc), revision=alert.revision, evidence=alert.evidence))

    def reconcile(self, run_id, rows, scopes):
        hits = {}
        for row in rows:
            for breach in row['rule_breaches']:
                key = f"{scope_key(row['scope'], row['scope_id'])}:{breach['code']}"
                hits.setdefault(key, []).append((row, breach))
        active = list(self.session.scalars(select(m.CongestionAlert).where(m.CongestionAlert.active_key.is_not(None))))
        active = {a.active_key: a for a in active if (a.scope, a.scope_id) in scopes}
        counts = dict(opened=0, refreshed=0, resolved=0, active=0)
        now = datetime.now(timezone.utc)
        for key, matches in sorted(hits.items()):
            matches.sort(key=lambda pair: pair[0]['timestamp'])
            row, breach = matches[0]
            evidence = dict(rule=breach, peak=max((b for _, b in matches), key=lambda b: b['evidence'].get('value', 0)),
                matching_hours=len(matches), matching_timestamps=[r['timestamp'].isoformat() for r, _ in matches])
            end = matches[-1][0]['timestamp'] + timedelta(hours=1)
            alert = active.pop(key, None)
            if alert:
                alert.last_run_id, alert.expected_start, alert.expected_end = run_id, row['timestamp'], end
                alert.duration_hours, alert.evidence = len(matches), evidence
                alert.updated_at, alert.revision = now, alert.revision + 1
                action = 'REFRESHED'
                counts['refreshed'] += 1
            else:
                alert = m.CongestionAlert(id=str(uuid4()), active_key=key, scope=row['scope'], scope_id=row['scope_id'],
                    port_id=row['port_id'], terminal_id=row['terminal_id'], berth_id=row['berth_id'], rule_code=breach['code'],
                    state='OPEN', revision=1, opened_at=now, updated_at=now, first_run_id=run_id, last_run_id=run_id,
                    expected_start=row['timestamp'], expected_end=end, duration_hours=len(matches), evidence=evidence)
                self.session.add(alert)
                self.session.flush()
                action = 'OPENED'
                counts['opened'] += 1
            self.event(alert, run_id, action)
        for alert in active.values():
            alert.state, alert.active_key, alert.resolved_at = 'RESOLVED', None, now
            alert.updated_at, alert.last_run_id, alert.revision = now, run_id, alert.revision + 1
            alert.evidence = dict(reason='Rule has no matching hours in the latest complete scoped forecast', previous=alert.evidence)
            self.event(alert, run_id, 'RESOLVED')
            counts['resolved'] += 1
        counts['active'] = len(hits)
        return counts

    def acknowledge(self, alert, actor, expected_revision):
        self.session.execute(update(m.AlertWatermark).where(m.AlertWatermark.id == scope_key(alert.scope, alert.scope_id))
            .values(revision=m.AlertWatermark.revision + 1))
        self.session.refresh(alert)
        if alert.state == 'RESOLVED':
            raise DomainError('ALERT_RESOLVED', 'A resolved alert cannot be acknowledged', 409)
        now = datetime.now(timezone.utc)
        changed = self.session.execute(update(m.CongestionAlert).where(m.CongestionAlert.id == alert.id,
            m.CongestionAlert.revision == expected_revision, m.CongestionAlert.state.in_(['OPEN', 'ACKNOWLEDGED']))
            .values(state='ACKNOWLEDGED', acknowledged_by=actor, acknowledged_at=now, updated_at=now,
                    revision=m.CongestionAlert.revision + 1), execution_options={'synchronize_session': False})
        if changed.rowcount != 1:
            raise DomainError('STALE_REVISION', 'Alert changed; fetch its current revision and retry', 409)
        self.session.refresh(alert)
        self.event(alert, alert.last_run_id, 'ACKNOWLEDGED', actor)
        return alert
