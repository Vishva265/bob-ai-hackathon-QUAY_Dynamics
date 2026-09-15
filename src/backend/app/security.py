"""Environment-backed operator access. Tokens contain no operational permissions."""
import hashlib
import hmac
import secrets
import time
from fastapi import APIRouter, Request, Response
from pydantic import Field
from app.schemas import DTO
from app.errors import DomainError

COOKIE = 'port_operator'
TTL = 7200
router = APIRouter(tags=['operator access'])

def authenticated(request):
    key = request.app.state.settings.operator_api_key
    if not key:
        return True
    supplied = request.headers.get('X-Operator-Key', '')
    if supplied and hmac.compare_digest(supplied.encode(), key.encode()):
        return True
    token = request.cookies.get(COOKIE, '')
    try:
        nonce, expiry, signature = token.split('.')
        payload = nonce+'.'+expiry
        expected = hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return len(nonce) == 32 and time.time() < int(expiry) <= time.time()+TTL and hmac.compare_digest(signature, expected)
    except (ValueError, TypeError):
        return False

class AccessInput(DTO):
    key: str = Field(min_length=1, max_length=512, repr=False)

@router.get('/auth/status')
def status(request: Request):
    return {'required': bool(request.app.state.settings.operator_api_key), 'authenticated': authenticated(request)}

@router.post('/auth/session')
def login(payload: AccessInput, request: Request, response: Response):
    key = request.app.state.settings.operator_api_key
    if not key or not hmac.compare_digest(payload.key.encode(), key.encode()):
        raise DomainError('ACCESS_DENIED', 'Invalid operator access key', 401)
    value = secrets.token_hex(16)+'.'+str(int(time.time())+TTL)
    signature = hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(COOKIE, value+'.'+signature, httponly=True,
        secure=request.app.state.settings.app_env == 'production', samesite='strict', max_age=TTL, path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'authenticated': True, 'expires_in_seconds': TTL}

@router.post('/auth/logout')
def logout(response: Response):
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
    return {'authenticated': False}
