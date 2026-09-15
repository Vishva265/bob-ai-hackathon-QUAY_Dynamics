"""Thin early-warning HTTP adapters."""
from typing import Literal
from fastapi import APIRouter

from app import schemas as s
from app.api.operations import DB, Limit
from app.services.early_warning import EarlyWarningService

Scope = Literal['port', 'terminal', 'berth']
RuleCode = Literal['BERTH_UTILISATION', 'YARD_OCCUPANCY', 'WAITING_TIME', 'CRANE_UTILISATION', 'ARRIVAL_SURGE', 'LOW_CONFIDENCE']
router = APIRouter(tags=['early warning'], responses={status: {'model': s.ErrorResponse} for status in (404, 409, 422, 503)})


@router.post('/early-warning/run', response_model=s.EarlyWarningRunOut, status_code=201)
def run(payload: s.EarlyWarningInput, db: DB):
    service = EarlyWarningService(db)
    return service.output(service.run(payload).id)


@router.get('/early-warning/rules', response_model=s.AlertRules)
def rules(db: DB):
    return EarlyWarningService(db).rules()


@router.get('/early-warning/runs/{run_id}', response_model=s.EarlyWarningRunOut)
def result(run_id: s.Identifier, db: DB):
    return EarlyWarningService(db).output(run_id)


@router.get('/early-warning/forecasts', response_model=s.OperationalForecastPage)
def forecasts(db: DB, limit: Limit = 25, cursor: str | None = None,
    run_id: s.Identifier | None = None, port_id: s.Identifier | None = None,
    terminal_id: s.Identifier | None = None, berth_id: s.Identifier | None = None,
    scope: Scope | None = None, start: s.UTC | None = None, end: s.UTC | None = None,
    hotspots_only: bool = False):
    return EarlyWarningService(db).buckets(limit, cursor, run_id, port_id, terminal_id, berth_id, scope, start, end, hotspots_only)


@router.get('/alerts', response_model=s.AlertPage)
def alerts(db: DB, limit: Limit = 25, cursor: str | None = None,
    port_id: s.Identifier | None = None, scope: Scope | None = None,
    scope_id: s.Identifier | None = None, state: Literal['OPEN', 'ACKNOWLEDGED', 'RESOLVED'] | None = None,
    rule_code: RuleCode | None = None):
    return EarlyWarningService(db).list_alerts(limit, cursor, port_id, scope, scope_id, state, rule_code)


@router.post('/alerts/{alert_id}/acknowledge', response_model=s.AlertOut)
def acknowledge(alert_id: s.Identifier, payload: s.ApprovalInput, db: DB):
    return EarlyWarningService(db).acknowledge(alert_id, payload)


@router.get('/alerts/{alert_id}/events', response_model=s.AlertEventPage)
def events(alert_id: s.Identifier, db: DB, limit: Limit = 25, cursor: str | None = None):
    return EarlyWarningService(db).events(alert_id, limit, cursor)
