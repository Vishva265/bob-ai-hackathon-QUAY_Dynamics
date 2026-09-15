"""HTTP adapters only; use cases live in services and persistence in repositories."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_session
from app import models as m, schemas as s
from app.repositories.operations import Repository
from app.services.operations import OperationsService
from app.services.forecasting import ForecastService
from app.services.planning import PlanningService
from app.services.prediction import PredictionService

router = APIRouter(responses={status: {'model': s.ErrorResponse} for status in (404, 409, 422, 503)})
DB = Annotated[Session, Depends(get_session, scope='function')]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get('/ports', response_model=s.PortPage, tags=['ports'])
def ports(db: DB, limit: Limit = 25, cursor: str | None = None, name: str | None = Query(default=None, max_length=120)):
    return OperationsService(db).ports(limit, cursor, name)


@router.get('/ports/{port_id}/status', response_model=s.PortStatus, tags=['ports'])
def port_status(port_id: s.Identifier, as_of: s.UTC, db: DB):
    return OperationsService(db).status(port_id, as_of)


@router.get('/vessel-calls', response_model=s.CallPage, tags=['vessel calls'])
def calls(db: DB, limit: Limit = 25, cursor: str | None = None,
          port_id: s.Identifier | None = None, terminal_id: s.Identifier | None = None,
          start: s.UTC | None = None, end: s.UTC | None = None,
          period: Literal['historical', 'upcoming'] | None = None,
          priority: int | None = Query(default=None, ge=1, le=5),
          cargo_type: Literal['general', 'reefer', 'hazardous'] | None = None,
          vessel_id: s.Identifier | None = None):
    return OperationsService(db).calls(limit, cursor, port_id, terminal_id, start, end, period, priority, cargo_type, vessel_id)


@router.post('/vessel-calls', response_model=s.CallOut, status_code=201, tags=['vessel calls'])
def create_call(payload: s.CallCreate, db: DB):
    return OperationsService(db).create_call(payload)


@router.get('/resources/availability', response_model=s.ResourcePage, tags=['resources'])
def resources(start: s.UTC, end: s.UTC, db: DB, limit: Limit = 25, cursor: str | None = None,
              port_id: s.Identifier | None = None, terminal_id: s.Identifier | None = None,
              resource_type: Literal['berth', 'crane', 'yard'] | None = None):
    return OperationsService(db).availability(start, end, limit, cursor, port_id, terminal_id, resource_type)


@router.get('/forecasts/congestion', response_model=s.ForecastPage, tags=['forecasts'])
def forecasts(db: DB, limit: Limit = 25, cursor: str | None = None, run_id: s.Identifier | None = None,
              port_id: s.Identifier | None = None, berth_id: s.Identifier | None = None,
              start: s.UTC | None = None, end: s.UTC | None = None):
    return ForecastService(db).list(limit, cursor, run_id, port_id, berth_id, start, end)


@router.post('/forecasts/run', response_model=s.ForecastRunOut, status_code=201, tags=['forecasts'])
def forecast_run(payload: s.ForecastInput, db: DB):
    service = ForecastService(db)
    return service.output(service.run(payload))


@router.get('/predictions/congestion', response_model=s.CongestionPredictionPage, tags=['predictions'])
def congestion_predictions(db: DB, limit: Limit = 25, cursor: str | None = None,
        run_id: s.Identifier | None = None, port_id: s.Identifier | None = None,
        terminal_id: s.Identifier | None = None, scope: Literal['port', 'terminal'] | None = None,
        start: s.UTC | None = None, end: s.UTC | None = None):
    return PredictionService(db).congestion(limit, cursor, run_id, port_id, terminal_id, scope, start, end)


@router.get('/predictions/waiting-time', response_model=s.WaitingPredictionPage, tags=['predictions'])
def waiting_predictions(db: DB, limit: Limit = 25, cursor: str | None = None,
        run_id: s.Identifier | None = None, call_id: s.Identifier | None = None,
        port_id: s.Identifier | None = None, terminal_id: s.Identifier | None = None):
    return PredictionService(db).waiting(limit, cursor, run_id, call_id, port_id, terminal_id)


@router.get('/predictions/models/current', response_model=s.ModelMetadataOut, tags=['predictions'])
def current_prediction_model(db: DB):
    return PredictionService(db).metadata()


@router.get('/optimisation/policy', response_model=s.OptimisationPolicy, tags=['optimisation'])
def optimisation_policy():
    return s.OptimisationPolicy.configured()


@router.post('/optimisation/run', response_model=s.OptimisationOut, status_code=201, tags=['optimisation'])
def optimise(payload: s.OptimisationInput, db: DB):
    service = PlanningService(db)
    return service.output(service.run(payload))


@router.get('/optimisation/{run_id}', response_model=s.OptimisationOut, tags=['optimisation'])
def optimisation(run_id: s.Identifier, db: DB):
    return PlanningService(db).output(Repository(db).get(m.OptimisationRun, run_id))


@router.get('/plans/72-hour', response_model=s.PlanOut, tags=['plans'])
def plan(db: DB, plan_id: s.Identifier | None = None, port_id: s.Identifier | None = None):
    return PlanningService(db).latest_plan(plan_id, port_id)


@router.post('/scenarios/simulate', response_model=s.OptimisationOut, status_code=201, tags=['scenarios'])
def scenario(payload: s.ScenarioInput, db: DB):
    service = PlanningService(db)
    return service.output(service.simulate(payload))


@router.post('/plans/{plan_id}/approve', response_model=s.PlanOut, tags=['plans'])
def approve(plan_id: s.Identifier, payload: s.ApprovalInput, db: DB):
    return PlanningService(db).approve(plan_id, payload)
