from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.database import alembic_config

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal['ok'] = 'ok'
    service: Literal['port-operations-api'] = 'port-operations-api'
    phase: Literal['operational_backend'] = 'operational_backend'


@router.get('/health', response_model=HealthResponse, tags=['system'])
def health() -> HealthResponse:
    """Process liveness only; no database or model readiness is claimed."""
    return HealthResponse()


class ReadinessResponse(BaseModel):
    status: Literal['ready', 'unavailable']
    database: str
    migration_revision: str | None = None
    model: dict | None = None
    data: dict | None = None


@router.get('/ready', response_model=ReadinessResponse, tags=['system'], responses={503: {'model': ReadinessResponse}})
def ready(request: Request):
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text('SELECT 1'))
            revision = MigrationContext.configure(connection).get_current_revision()
        head = ScriptDirectory.from_config(alembic_config()).get_current_head()
        if revision != head:
            return JSONResponse(status_code=503, content=dict(status='unavailable', database='migration_required', migration_revision=revision))
        from app.predictive.registry import ModelRegistry, ModelArtifactError
        required = request.app.state.settings.readiness_require_model
        try:
            _, metadata = ModelRegistry(request.app.state.settings.model_directory).load()
            model = dict(status='available', required=required, version=metadata['model_version'], quality=metadata['quality'])
        except ModelArtifactError:
            model = dict(status='unavailable', required=required)
        from sqlalchemy import select, func
        from app import models as m
        with request.app.state.engine.connect() as connection:
            counts = {table.__tablename__: connection.scalar(select(func.count()).select_from(table))
                for table in (m.Port,m.Terminal,m.Berth,m.Crane)}
        data = dict(status='available' if all(counts.values()) else 'unavailable',
            required=request.app.state.settings.readiness_require_data, resource_counts=counts)
        unavailable = (required and model['status'] != 'available') or (data['required'] and data['status']!='available')
        result = dict(status='unavailable' if unavailable else 'ready',
            database=request.app.state.engine.dialect.name, migration_revision=revision, model=model, data=data)
        return JSONResponse(status_code=503, content=result) if result['status']=='unavailable' else result
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content=dict(status='unavailable', database='unreachable', migration_revision=None))
