"""Failure paths and CPU admission controls use actual FastAPI/DB boundaries."""
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func, update, event
from sqlalchemy.exc import OperationalError
from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.main import create_app
from app.jobs import JobLock
from app.services.planning import PlanningService
from app.services.demo_startup import seed_demo
from app.synthetic.files import export_dataset
from test_operations_api import source, api, EPOCH

KEY = 'test-only-operator-secret-'+'x'*32

def client(tmp_path, **options):
    settings=replace(get_settings(),database_url='sqlite:///'+str(tmp_path/'review.db'),**options)
    return TestClient(create_app(settings))

def test_auth_key_cookie_tamper_logout_and_alias_protection(tmp_path):
    with client(tmp_path,operator_api_key=KEY) as c:
        assert c.get('/health').status_code==200
        assert c.get('/api/v1/auth/status').json()=={'required':True,'authenticated':False}
        for path in ('/ports','/api/v1/ports'):
            denied=c.get(path);assert denied.status_code==401
            assert denied.json()['error']['request_id']==denied.headers['X-Request-ID']
        assert c.post('/auth/session',json={'key':'incorrect'}).status_code==401
        login=c.post('/api/v1/auth/session',json={'key':KEY})
        assert login.status_code==200 and 'HttpOnly' in login.headers['set-cookie'] and 'SameSite=strict' in login.headers['set-cookie']
        assert KEY not in login.text and c.get('/ports').status_code==200
        token=c.cookies.get('port_operator');c.cookies.clear();c.cookies.set('port_operator',token+'bad')
        assert c.get('/ports').status_code==401
        assert c.get('/ports',headers={'X-Operator-Key':KEY}).status_code==200
        c.cookies.clear();c.post('/auth/session',json={'key':KEY});assert c.post('/auth/logout').status_code==200
        assert c.get('/ports').status_code==401

def test_login_rate_limit_and_production_cookie(tmp_path):
    with client(tmp_path,operator_api_key=KEY) as c:
        for _ in range(5):assert c.post('/auth/session',json={'key':'wrong'}).status_code==401
        limited=c.post('/auth/session',json={'key':KEY});assert limited.status_code==429
        assert limited.headers['Retry-After']=='60'
    # Production settings can be exercised against a dedicated test engine only.
    settings=replace(get_settings(),app_env='production',operator_api_key=KEY,auto_migrate=True)
    with TestClient(create_app(settings,make_engine('sqlite:///:memory:')),base_url='https://testserver') as c:
        assert 'Secure' in c.post('/auth/session',json={'key':KEY}).headers['set-cookie']

def test_untrusted_origins_cannot_submit_cookie_authenticated_mutations(tmp_path):
    with client(tmp_path,operator_api_key=KEY) as c:
        assert c.post('/auth/session',json={'key':KEY}).status_code==200
        denied=c.post('/auth/logout',headers={'Origin':'https://evil.example'})
        assert denied.status_code==403 and denied.json()['error']['code']=='ORIGIN_NOT_ALLOWED'
        assert c.get('/auth/status').json()['authenticated']

def test_production_configuration_requires_secrets_and_rejects_unsafe_options(monkeypatch):
    monkeypatch.setenv('APP_ENV','production');monkeypatch.setenv('DATABASE_URL','postgresql://user:secret@localhost/db')
    monkeypatch.delenv('OPERATOR_API_KEY',raising=False)
    with pytest.raises(ValueError,match='OPERATOR_API_KEY'):get_settings()
    monkeypatch.setenv('OPERATOR_API_KEY',KEY)
    assert get_settings().readiness_require_model and KEY not in repr(get_settings())
    monkeypatch.setenv('DEMO_SEED_ON_START','true')
    with pytest.raises(ValueError,match='prohibited'):get_settings()

@pytest.mark.parametrize('options',[{'cors_origins':('*',)},{'cors_origins':('https://host/path',)},
    {'operator_api_key':'short'},{'request_body_limit_bytes':0},{'expensive_requests_per_minute':0},{'job_lease_seconds':1}])
def test_settings_reject_invalid_limits(options):
    with pytest.raises(ValueError):replace(get_settings(),**options)

def test_body_limit_measures_declared_and_chunked_bodies(tmp_path):
    with client(tmp_path,request_body_limit_bytes=1024) as c:
        for payload in ('x'*2048,iter([b'x'*700,b'x'*700])):
            r=c.post('/vessel-calls',content=payload,headers={'Content-Type':'application/json'})
            assert r.status_code==413 and r.json()['error']['code']=='REQUEST_TOO_LARGE'
        r=c.post('/vessel-calls',content='{bad',headers={'Content-Type':'application/json'})
        assert r.status_code==422 and r.json()['error']['code']=='VALIDATION_ERROR'

def test_expensive_rate_budget_shared_by_root_alias_and_canonical_path(tmp_path):
    with client(tmp_path,expensive_requests_per_minute=1) as c:
        first=c.post('/optimisation/run',json={});assert first.status_code==422
        second=c.post('/api/v1/optimisation/run',json={})
        assert second.status_code==429 and second.headers['Retry-After']=='60'
        assert c.get('/health').status_code==200

def test_concurrent_optimisations_rejected_then_lock_released(api,monkeypatch):
    entered=threading.Event();resume=threading.Event();real=PlanningService.run
    def controlled(self,*args,**kwargs):
        entered.set();assert resume.wait(15)
        return real(self,*args,**kwargs)
    monkeypatch.setattr(PlanningService,'run',controlled)
    body={'as_of':EPOCH,'port_ids':['P04'],'time_limit_seconds':.1}
    with ThreadPoolExecutor(max_workers=2) as workers:
        first=workers.submit(api.post,'/optimisation/run',json=body)
        assert entered.wait(15)
        try:
            second=api.post('/api/v1/optimisation/run',json=body)
            assert second.status_code==409 and second.json()['error']['code']=='OPTIMISATION_BUSY'
        finally:resume.set()
        assert first.result(timeout=60).status_code==201
    with api.app.state.sessions() as db:assert db.scalar(select(func.count()).select_from(m.OptimisationJobLease))==0
    assert api.post('/optimisation/run',json=body).status_code==201

def test_independent_engines_share_leases_expiry_and_owner_checked_release(tmp_path):
    url='sqlite:///'+str(tmp_path/'locks.db');one=make_engine(url);two=make_engine(url);migrate(one)
    a=JobLock(one).acquire();b=JobLock(two)
    try:
        with pytest.raises(Exception,match='already running'):b.acquire()
        with one.begin() as db:db.execute(update(m.OptimisationJobLease).values(expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
        b.acquire();a.release()
        with session_factory(two)() as db:assert db.get(m.OptimisationJobLease,b.id).owner==b.owner
        assert b.renew()
    finally:b.release();one.dispose();two.dispose()

def test_database_unavailable_has_safe_errors_liveness_and_cors(tmp_path):
    with client(tmp_path) as c:
        engine=c.app.state.engine
        def unavailable(*_):raise OperationalError('secret SQL and credentials',{},Exception('secret'))
        event.listen(engine,'before_cursor_execute',unavailable)
        try:
            assert c.get('/health').status_code==200
            assert c.get('/ready').status_code==503
            for method,path in [('get','/ports'),('post','/optimisation/run')]:
                r=getattr(c,method)(path,headers={'Origin':'http://localhost:5173'})
                assert r.status_code==503 and 'secret' not in r.text
                assert r.headers['access-control-allow-origin']=='http://localhost:5173'
        finally:event.remove(engine,'before_cursor_execute',unavailable)

def test_unexpected_errors_have_request_id_and_cors_without_details(tmp_path):
    c=client(tmp_path)
    @c.app.get('/testing/boom')
    def boom():raise RuntimeError('private secret')
    with c:
        r=c.get('/testing/boom',headers={'Origin':'http://localhost:5173'})
        assert r.status_code==500 and 'private secret' not in r.text
        assert r.json()['error']['request_id']==r.headers['X-Request-ID']
        assert r.headers['access-control-allow-origin']=='http://localhost:5173'

def test_missing_model_readiness_and_api_never_claim_predictions(tmp_path):
    with client(tmp_path,readiness_require_model=True) as c:
        assert c.get('/health').status_code==200
        r=c.get('/ready');assert r.status_code==503 and r.json()['model']=={'status':'unavailable','required':True}
        r=c.get('/predictions/models/current');assert r.status_code==503 and r.json()['error']['code']=='MODEL_UNAVAILABLE'

def test_required_resource_data_keeps_empty_database_unready(tmp_path):
    with client(tmp_path,readiness_require_data=True) as c:
        assert c.get('/health').status_code==200
        r=c.get('/ready');assert r.status_code==503 and r.json()['data']['status']=='unavailable'

def test_seed_on_start_is_opt_in_idempotent_and_never_overwrites(source,tmp_path):
    folder=tmp_path/'data';export_dataset(folder,*source)
    settings=replace(get_settings(),database_url='sqlite:///'+str(tmp_path/'seed.db'),demo_seed_on_start=True,demo_dataset_directory=str(folder))
    with TestClient(create_app(settings)) as c:
        assert len(c.get('/ports').json()['items'])==4
        assert c.get('/dashboard').status_code==200
    with TestClient(create_app(settings)) as c:
        assert len(c.get('/ports').json()['items'])==4
        with c.app.state.sessions() as db:
            assert db.scalar(select(func.count()).select_from(m.SeedProvenance))==1
            assert db.scalar(select(func.count()).select_from(m.OptimisationRun))==1


def test_infeasible_api_schedule_is_audited_and_cannot_be_approved(api):
    start=EPOCH;end='2026-09-18T00:00:00Z'
    request={'name':'Full severe wind closure','as_of':EPOCH,'port_ids':['P04'],
        'overrides':[{'kind':'storm','port_id':'P04','start':start,'end':end}],
        'policy':{'allow_deferral':False},'time_limit_seconds':.1}
    r=api.post('/scenarios/simulate',json=request)
    assert r.status_code==201,r.text
    run=r.json();assert run['solver_status']=='INFEASIBLE' and run['status']=='failed'
    assert run['diagnostics']['infeasibility_explanations'] and not run['metrics']['validation_passed']
    assert api.post('/plans/'+run['plan']['id']+'/approve',json={'actor':'Supervisor','expected_revision':1}).status_code==409


@pytest.mark.skipif(not __import__('os').getenv('PORT_OPERATIONS_TEST_DATABASE_URL'),reason='Dedicated PostgreSQL test URL not configured')
def test_postgresql_job_lock_shared_across_connections():
    import os
    from uuid import uuid4
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema,DropSchema
    admin=make_engine(os.environ['PORT_OPERATIONS_TEST_DATABASE_URL']);schema='lease_test_'+uuid4().hex
    with admin.begin() as db:db.execute(CreateSchema(schema))
    url=make_url(os.environ['PORT_OPERATIONS_TEST_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+schema}).render_as_string(hide_password=False)
    one=make_engine(url);two=make_engine(make_url(url).set(host='localhost').render_as_string(hide_password=False))
    try:
        migrate(one);first=JobLock(one).acquire();second=JobLock(two)
        with pytest.raises(Exception,match='already running'):second.acquire()
        first.release();second.acquire();assert second.renew();second.release()
    finally:
        one.dispose();two.dispose()
        with admin.begin() as db:db.execute(DropSchema(schema,cascade=True))
        admin.dispose()
