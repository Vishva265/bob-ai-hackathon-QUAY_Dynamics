from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException


class DomainError(Exception):
    def __init__(self, code, message, status=422, details=None):
        self.code, self.message, self.status = code, message, status
        self.details = details or []


def response(request, status, code, message, details=None):
    return JSONResponse(status_code=status, content={'error': dict(code=code, message=message,
        details=details or [], request_id=getattr(request.state, 'request_id', None))})


def register_errors(app):
    @app.exception_handler(DomainError)
    async def domain(request: Request, error: DomainError):
        return response(request, error.status, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError):
        details = [{'field': '.'.join(str(v) for v in e['loc']), 'reason': e['msg']} for e in error.errors()]
        return response(request, 422, 'VALIDATION_ERROR', 'Request validation failed', details)

    @app.exception_handler(HTTPException)
    async def http(request: Request, error: HTTPException):
        return response(request, error.status_code, 'NOT_FOUND' if error.status_code == 404 else 'HTTP_ERROR', str(error.detail))

    @app.exception_handler(IntegrityError)
    async def integrity(request: Request, error: IntegrityError):
        return response(request, 409, 'DATA_CONFLICT', 'Data conflicts with an existing record or database constraint')

    @app.exception_handler(SQLAlchemyError)
    async def database(request: Request, error: SQLAlchemyError):
        return response(request, 503, 'DATABASE_UNAVAILABLE', 'Database is unavailable; retry after checking service readiness')

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception):
        from app.observability import logger
        logger.error('unhandled_error', extra={'fields': dict(request_id=getattr(request.state, 'request_id', None), error_type=type(error).__name__)})
        return response(request, 500, 'INTERNAL_ERROR', 'An unexpected server error occurred')
