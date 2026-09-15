"""Bound request bodies, operator access, expensive budgets and durable job locks."""
import asyncio
import re
import time
from collections import OrderedDict, deque
from threading import Lock
from starlette.requests import Request
from sqlalchemy.exc import SQLAlchemyError
from app.errors import DomainError, response
from app.jobs import JobLock
from app.observability import logger
from app.security import authenticated

class Budget:
    def __init__(self):
        self.clients = OrderedDict()
        self.lock = Lock()

    def accept(self, key, maximum):
        now = time.monotonic()
        with self.lock:
            queue = self.clients.setdefault(key, deque())
            self.clients.move_to_end(key)
            while queue and queue[0] <= now-60:
                queue.popleft()
            while len(self.clients) > 10000:
                self.clients.popitem(last=False)
            if len(queue) >= maximum:
                return False
            queue.append(now)
            return True

class RequestGuard:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings
        self.budget = Budget()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        path = re.sub(r'^/api(?:/v1)?(?=/|$)', '', request.url.path)
        branch = re.match(r'^/live-demo/([a-f0-9]{32})(?=/|$)', path)
        action = path[branch.end():] if branch else path
        expensive = request.method == 'POST' and (action.endswith(('/run', '/replan', '/simulate', '/scenarios', '/query', '/ask', '/what-if', '/events', '/retry')) or path == '/live-demo/sessions')
        locked = expensive and not action.endswith(('/query','/ask'))
        public = path in ('/health', '/ready', '/auth/status', '/auth/session', '/auth/logout', '/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json')
        job = None
        heartbeat = None
        started = False
        async def tracked_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            origin = request.headers.get('origin')
            own_origin = str(request.base_url).rstrip('/')
            if request.method=='POST' and origin and origin not in (*self.settings.cors_origins,own_origin):
                raise DomainError('ORIGIN_NOT_ALLOWED', 'This origin is not allowed to submit operational changes', 403)
            if request.method != 'OPTIONS' and not public and not authenticated(request):
                raise DomainError('OPERATOR_ACCESS_REQUIRED', 'Operator access required. Open Operator access in the dashboard header.', 401)
            peer = request.client.host if request.client else 'unknown'
            if path == '/auth/session' and not self.budget.accept(('login', peer), 5):
                raise DomainError('RATE_LIMITED', 'Too many login attempts; retry in 60 seconds', 429)
            if expensive and not self.budget.accept(('expensive', peer), self.settings.expensive_requests_per_minute):
                raise DomainError('RATE_LIMITED', 'Expensive operation budget exceeded; retry in 60 seconds', 429)
            # Buffer only bounded POST bodies before domain work. Chunked bodies
            # obey the same measured limit as Content-Length bodies.
            if request.method == 'POST':
                declared = request.headers.get('content-length')
                if declared and (not declared.isdigit() or len(declared)>12 or int(declared) > self.settings.request_body_limit_bytes):
                    raise DomainError('REQUEST_TOO_LARGE', 'Request body exceeds the configured limit', 413)
                payload = bytearray()
                while True:
                    chunk = await receive()
                    if chunk['type'] == 'http.disconnect':
                        return
                    payload.extend(chunk.get('body', b''))
                    if len(payload) > self.settings.request_body_limit_bytes:
                        raise DomainError('REQUEST_TOO_LARGE', 'Request body exceeds the configured limit', 413)
                    if not chunk.get('more_body', False):
                        break
                consumed = False
                upstream = receive
                async def bounded_receive():
                    nonlocal consumed
                    if consumed:
                        return await upstream()
                    consumed = True
                    return {'type': 'http.request', 'body': bytes(payload), 'more_body': False}
                receive = bounded_receive
            if locked:
                engine = await asyncio.to_thread(request.app.state.live_demo.branch, branch.group(1)) if branch else request.app.state.engine
                job = JobLock(engine, self.settings.job_lease_seconds)
                await asyncio.to_thread(job.acquire)
                async def renew():
                    while True:
                        await asyncio.sleep(self.settings.job_lease_seconds/3)
                        try:
                            retained = await asyncio.to_thread(job.renew)
                        except SQLAlchemyError:
                            logger.error('job_lease_renew_failed', extra={'fields': {'job_id': job.owner}})
                            return
                        if not retained:
                            logger.error('job_lease_lost', extra={'fields': {'job_id': job.owner}})
                            return
                heartbeat = asyncio.create_task(renew())
            await self.app(scope, receive, tracked_send)
        except Exception as error:
            if started:
                raise
            if isinstance(error, DomainError):
                result = response(request, error.status, error.code, error.message, error.details)
            elif isinstance(error, SQLAlchemyError):
                result = response(request, 503, 'DATABASE_UNAVAILABLE', 'Database is unavailable; check service readiness')
            else:
                logger.error('request_guard_error', extra={'fields': {'error_type': type(error).__name__}})
                result = response(request, 500, 'INTERNAL_ERROR', 'An unexpected server error occurred')
            if result.status_code in (429, 409):
                result.headers['Retry-After'] = '60' if result.status_code == 429 else '2'
            await result(scope, receive, send)
        finally:
            if heartbeat:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
            if job:
                try:
                    await asyncio.to_thread(job.release)
                except SQLAlchemyError:
                    logger.error('job_lease_release_failed', extra={'fields': {'job_id': job.owner}})
