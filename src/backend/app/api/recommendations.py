"""HTTP adapters; all calculations live in recommendation domain/services."""
from fastapi import APIRouter
from app.api.operations import DB, Limit
from app.schemas import ErrorResponse, Identifier
from app.recommendations import schemas as s
from app.services.recommendations import RecommendationService

router = APIRouter(tags=['routing and arrival recommendations'], responses={status: {'model': ErrorResponse} for status in (404, 409, 422, 503)})


@router.get('/recommendations/policy', response_model=s.RecommendationPolicy)
def policy(db: DB):
    return RecommendationService(db).policy()


@router.post('/recommendations/run', response_model=s.RecommendationRunOut, status_code=201)
def run(payload: s.RecommendationInput, db: DB):
    service = RecommendationService(db)
    return service.output(service.run(payload).id)


@router.post('/recommendations/what-if', response_model=s.RecommendationRunOut, status_code=201)
def what_if(payload: s.WhatIfInput, db: DB):
    service = RecommendationService(db)
    return service.output(service.run(payload).id)


@router.get('/recommendations/runs/{run_id}', response_model=s.RecommendationRunOut)
def result(run_id: Identifier, db: DB):
    return RecommendationService(db).output(run_id)


@router.get('/recommendations', response_model=s.RecommendationPage)
def decisions(db: DB, limit: Limit = 25, cursor: str | None = None, run_id: Identifier | None = None,
    port_id: Identifier | None = None, call_id: Identifier | None = None, action: s.Action | None = None):
    return RecommendationService(db).list(limit, cursor, run_id, port_id, call_id, action)
