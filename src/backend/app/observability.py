import json
import logging
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from datetime import datetime, timezone
        payload = dict(timestamp=datetime.now(timezone.utc).isoformat(), level=record.levelname,
                       event=record.getMessage())
        payload.update(getattr(record, 'fields', {}))
        return json.dumps(payload)


logger = logging.getLogger('port_operations')
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.request_id = str(uuid4())
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers['X-Request-ID'] = request.state.request_id
            return response
        finally:
            logger.info('http_request', extra={'fields': dict(request_id=request.state.request_id,
                method=request.method, path=request.url.path, status=status,
                duration_ms=round((time.perf_counter()-started)*1000, 2))})
