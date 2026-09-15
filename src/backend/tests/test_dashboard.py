import copy
from app import models as m
from sqlalchemy import select
from test_operations_api import api,source,EPOCH


def test_dashboard_requires_seed_and_returns_exact_operational_scope(api):
    assert api.get('/dashboard').status_code==404
    response=api.post('/optimisation/run',json={'as_of':EPOCH,'port_ids':['P04'],'predictor':'baseline','time_limit_seconds':1})
    run=response.json()
    dashboard=api.get('/dashboard',params={'run_id':run['id']})
    assert dashboard.status_code==200,dashboard.text
    value=dashboard.json()
    assert value['run']['metrics']==run['metrics']
    assert {p['id'] for p in value['inventory']['routing_ports']}=={'P04'}
    assert value['forecast_rows']==[] and value['risk_wait_threshold_hours']==8
    assert len(value['run']['plan']['shifts'])==9
    assert {a['call_id'] for a in value['effective_assignments']}=={a['call_id'] for a in run['assignments']}
    assert api.get('/dashboard',params={'run_id':'MISSING'}).status_code==404


def test_dashboard_scenario_uses_real_source_and_isolates_operational_changes(api):
    run=api.post('/optimisation/run',json={'as_of':EPOCH,'port_ids':['P04'],'predictor':'baseline','time_limit_seconds':1}).json()
    with api.app.state.sessions() as session:
        before={c.id:c.scheduled_eta for c in session.scalars(select(m.VesselCall))}
    payload={'source_run_id':run['id'],'port_id':'P04','arrival_compression_pct':50,'weather_severity':1,'yard_capacity_pct':90,'time_limit_seconds':1}
    result=api.post('/dashboard/scenarios',json=payload)
    assert result.status_code==201,result.text
    scenario=result.json()
    assert scenario['scenario_id'] and len(scenario['plan']['shifts'])==9
    with api.app.state.sessions() as session:
        assert {c.id:c.scheduled_eta for c in session.scalars(select(m.VesselCall))}==before
        assert session.get(m.OptimisationRun,scenario['id']).input_snapshot['overrides']
    invalid=dict(payload,port_id='P01')
    assert api.post('/dashboard/scenarios',json=invalid).status_code==422
    invalid=dict(payload,arrival_compression_pct=-1)
    assert api.post('/dashboard/scenarios',json=invalid).status_code==422


def test_empty_scenario_and_duplicate_outages_are_rejected(api):
    run=api.post('/optimisation/run',json={'as_of':EPOCH,'port_ids':['P04'],'predictor':'baseline','time_limit_seconds':1}).json()
    payload={'source_run_id':run['id'],'port_id':'P04'}
    assert api.post('/dashboard/scenarios',json=payload).json()['error']['code']=='EMPTY_SCENARIO'
    payload['crane_ids']=['C','C']
    assert api.post('/dashboard/scenarios',json=payload).json()['error']['code']=='DUPLICATE_CRANES'
