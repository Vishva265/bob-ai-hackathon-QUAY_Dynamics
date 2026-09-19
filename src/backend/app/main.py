from fastapi import FastAPI, Depends
import os
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database import make_engine, migrate, session_factory
from app.errors import register_errors
from app.observability import RequestLoggingMiddleware, logger
from app.api.operations import router as operations_router
from app.api.early_warning import router as early_warning_router
from app.api.recommendations import router as recommendation_router
from app.api.plans import router as plan_router
from app.api.dashboard import router as dashboard_router
from app.api.copilot import router as copilot_router
from app.api.live_demo import router as live_demo_router, demo_context
from app.api.evaluation import router as evaluation_router
from app.api.historical_replay import router as historical_router, historical_context
from app.api.data_lab import router as data_lab_router
from app.services.live_demo import LiveDemoManager

from app.api.health import router
from app.config import get_settings
from app.request_guard import RequestGuard
from app.security import router as security_router
from app.schemas import ErrorResponse
from sqlalchemy.exc import SQLAlchemyError


def create_app(settings=None, engine=None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if settings.auto_migrate:
            migrate(engine)
        if settings.demo_seed_on_start:
            from app.services.demo_startup import seed_demo
            seed_demo(engine, settings)
        try:
            app.state.live_demo.recover()
        except SQLAlchemyError:
            logger.error('demo_recovery_database_unavailable')
        logger.info('application_started', extra={'fields': dict(environment=settings.app_env, database=engine.dialect.name)})
        yield
        app.state.live_demo.dispose()
        engine.dispose()
    app = FastAPI(
        title='Container Congestion Predictor & Port Operations Optimiser',
        version='0.12.0',
        description='Operational data and versioned synthetic-trained predictions. Berth-capacity baselines support CP-SAT plans with explicit assumptions.',
        lifespan=lifespan,
        responses={status: {'model': ErrorResponse} for status in (401,403,409,413,422,429,500,503)},
    )
    app.add_middleware(RequestGuard, settings=settings)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=['GET', 'POST'],
        allow_headers=['Content-Type', 'X-Operator-Key', 'Last-Event-ID'],
        allow_credentials=True,
        expose_headers=['X-Request-ID', 'Retry-After'],
    )
    app.state.engine = engine
    app.state.sessions = session_factory(engine)
    app.state.settings = settings
    app.state.live_demo = LiveDemoManager(engine, enabled=os.getenv('LIVE_DEMO_ENABLED',
        'false' if settings.app_env=='production' else 'true').lower()=='true')
    register_errors(app)
    app.include_router(security_router, prefix='/api/v1')
    app.include_router(evaluation_router, prefix='/api/v1')
    app.include_router(historical_router, prefix='/api/v1')
    for adapter in (dashboard_router, copilot_router, plan_router, data_lab_router, early_warning_router):
        app.include_router(adapter, prefix='/api/v1/historical', dependencies=[Depends(historical_context)], include_in_schema=False)
    app.include_router(data_lab_router, prefix='/api/v1')
    app.include_router(security_router, include_in_schema=False)
    app.include_router(router, prefix='/api/v1')
    app.include_router(operations_router, prefix='/api/v1')
    app.include_router(early_warning_router, prefix='/api/v1')
    app.include_router(recommendation_router, prefix='/api/v1')
    app.include_router(plan_router, prefix='/api/v1')
    app.include_router(dashboard_router,prefix='/api/v1')
    app.include_router(copilot_router,prefix='/api/v1')
    app.include_router(copilot_router,prefix='/api')
    app.include_router(live_demo_router,prefix='/api/v1')
    # Existing APIs use the private branch through request-scoped dependencies.
    # No global engine switching, proxy forwarding or main-data mutation.
    for adapter in (operations_router, early_warning_router, recommendation_router, plan_router, dashboard_router, copilot_router, data_lab_router):
        app.include_router(adapter,prefix='/api/v1/live-demo/{demo_id}',dependencies=[Depends(demo_context)],include_in_schema=False)
    # Root aliases honour the requested endpoint spellings; canonical docs use v1.
    app.include_router(router, include_in_schema=False)
    app.include_router(operations_router, include_in_schema=False)
    app.include_router(early_warning_router, include_in_schema=False)
    app.include_router(recommendation_router, include_in_schema=False)
    app.include_router(plan_router, include_in_schema=False)
    app.include_router(dashboard_router,include_in_schema=False)
    app.include_router(copilot_router,include_in_schema=False)
    return app


app = create_app()
