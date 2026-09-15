from fastapi.testclient import TestClient

from app.main import create_app
from app.database import make_engine


def test_health_and_openapi():
    with TestClient(create_app(engine=make_engine('sqlite:///:memory:'))) as client:
        response = client.get('/api/v1/health')
        assert response.status_code == 200
        assert response.json() == {
            'status': 'ok', 'service': 'port-operations-api', 'phase': 'operational_backend'
        }
        assert '/api/v1/health' in client.get('/openapi.json').json()['paths']


def test_cors_allows_local_frontend_and_rejects_unknown_origin():
    with TestClient(create_app(engine=make_engine('sqlite:///:memory:'))) as client:
        allowed = client.get('/api/v1/health', headers={'Origin': 'http://localhost:5173'})
        assert allowed.headers['access-control-allow-origin'] == 'http://localhost:5173'
        denied = client.get('/api/v1/health', headers={'Origin': 'https://unknown.example'})
        assert 'access-control-allow-origin' not in denied.headers
