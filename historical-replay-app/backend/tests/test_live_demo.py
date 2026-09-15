import hashlib
import json
import os
from uuid import uuid4
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema
from app import models as m
from app.config import get_settings
from app.database import make_engine,migrate,session_factory
from app.errors import DomainError
from app.main import create_app
from app.live.schemas import EventInput
from app.live.simulation import observe_tick
from app.optimisation.resources import Resources
from app.predictive.inference import InferenceEngine
from app.services.context import snapshot_inputs
from app.services.live_demo import LiveDemoManager,impact
from app.services.seed import seed_tables
from app.services.supervisor_plans import SupervisorPlanService
from app.synthetic.simulator import parse
from test_predictive import trained
from test_operations_api import source,EPOCH


@pytest.fixture
def live_api(source,trained,tmp_path,monkeypatch):
    monkeypatch.setenv('MODEL_DIRECTORY',str(trained[0].directory));monkeypatch.setenv('LIVE_DEMO_DIRECTORY',str(tmp_path/'branches'))
    monkeypatch.setenv('LIVE_DEMO_ENABLED','true')
    engine=make_engine('sqlite:///'+(tmp_path/'operations.db').as_posix());migrate(engine)
    with session_factory(engine).begin() as db:seed_tables(db,*source)
    captured={};original=InferenceEngine.forecast
    def inference(self,tables,*args,**kwargs):
        captured['tables']=tables
        return original(self,tables,*args,**kwargs)
    monkeypatch.setattr(InferenceEngine,'forecast',inference)
    with TestClient(create_app(replace(get_settings(),auto_migrate=False),engine)) as client:
        client.app.state.captured_inference=captured
        yield client


def digest(engine):
    with engine.connect() as db:
        result={}
        for table in m.Base.metadata.sorted_tables:
            if table.name.startswith('live_demo_'):continue
            rows=[dict(r) for r in db.execute(select(table)).mappings()]
            result[table.name]=hashlib.sha256(json.dumps(sorted(rows,key=lambda r:json.dumps(r,sort_keys=True,default=str)),sort_keys=True,default=str).encode()).hexdigest()
        return result


def start(api):
    response=api.post('/api/v1/live-demo/sessions',json={'port_id':'P04','time_limit_seconds':.5,'seed':42})
    assert response.status_code==201,response.text
    return response.json()


def inject(api,demo,kind,**kwargs):
    state=api.get('/api/v1/live-demo/'+demo['id']).json()
    response=api.post('/api/v1/live-demo/'+demo['id']+'/events',json={'kind':kind,'expected_revision':state['revision'],**kwargs})
    assert response.status_code==202,response.text
    result=api.get('/api/v1/live-demo/'+demo['id']+'/events').json()['items'][0]
    assert result['status']=='SUCCEEDED',result
    return result


def test_all_event_types_persist_update_forecast_replan_and_isolate_source(live_api):
    api=live_api;manager=api.app.state.live_demo;before=digest(manager.engine);demo=start(api)
    engine=manager.branch(demo['id']);prefix='/api/v1/live-demo/'+demo['id']
    with session_factory(engine)() as db:
        data=snapshot_inputs(db,parse(demo['clock']),['P04'])
        carried={c['call_id'] for c in data['carry_in']}
        calls=[c for c in data['calls'] if c['id'] not in carried and parse(c['scheduled_eta'])>parse(demo['clock'])+timedelta(hours=12)]
        owned={cid for c in data['carry_in'] for cid in c['crane_ids']}
        crane=next(c for c in data['cranes'] if c['id'] not in owned)
        berth=next(b for b in data['berths'] if b['id'] not in {c['berth_id'] for c in data['carry_in']})
        terminal=data['terminals'][0]
    cases=[('eta_delay',{'call_id':calls[0]['id'],'hours':6}),('early_arrival',{'call_id':calls[1]['id'],'hours':2}),
        ('crane_breakdown',{'crane_id':crane['id']}),('crane_recovery',{'crane_id':crane['id']}),
        ('severe_wind',{'wind_mps':18}),('yard_capacity_reduction',{'terminal_id':terminal['id'],'capacity_pct':99}),
        ('berth_closure',{'berth_id':berth['id'],'duration_hours':2}),('priority_arrival',{'call_id':calls[2]['id']})]
    for kind,kwargs in cases:
        event=inject(api,demo,kind,**kwargs);result=event['result']
        assert result['approval_required'] and not result['operational_plan_replaced']
        assert result['plan_status']=='DRAFT' and result['forecast_runtime_ms']>=0 and result['optimisation_runtime_ms']>=0
        with session_factory(engine)() as db:
            run=db.get(m.OptimisationRun,result['new_run_id'])
            assert db.get(m.LiveDemoReceipt,event['id']).run_id==run.id
            assert db.get(m.EarlyWarningRun,run.forecast_run_id)
            current=snapshot_inputs(db,parse(run.as_of),['P04']);resources=Resources(current)
            assert all(parse(y['timestamp'])==parse(run.as_of) for y in current['yards'])
            if kind=='eta_delay':assert parse(db.get(m.VesselCall,calls[0]['id']).scheduled_eta)==parse(calls[0]['scheduled_eta'])+timedelta(hours=6)
            if kind=='early_arrival':assert parse(db.get(m.VesselCall,calls[1]['id']).scheduled_eta)==parse(calls[1]['scheduled_eta'])-timedelta(hours=2)
            if kind=='crane_breakdown':
                assert not any(resources.available[crane['id']])
                assert all(parse(a['end'])>=parse(run.end) for a in current['availability'] if a['crane_id']==crane['id'] and a['reason']=='breakdown')
            if kind=='crane_recovery':
                assert not any(a['crane_id']==crane['id'] and a['reason']=='breakdown' for a in current['availability'])
                model_rows=api.app.state.captured_inference['tables']['crane_availability']
                assert all(parse(a['end'])<=parse(run.as_of) for a in model_rows if a['crane_id']==crane['id'] and a['reason']=='breakdown')
                availability=api.get(prefix+'/resources/availability',params={'start':run.as_of,'end':run.end,'port_id':'P04','resource_type':'crane','limit':100}).json()
                assert not any(i['reason']=='breakdown' for resource in availability['items'] if resource['id']==crane['id'] for i in resource['unavailable_intervals'])
            if kind=='severe_wind':assert current['weather'][0]['wind_mps']==18
            if kind=='yard_capacity_reduction':assert next(t['yard_capacity_teu'] for t in current['terminals'] if t['id']==terminal['id'])==pytest.approx(terminal['yard_capacity_teu']*.99)
            if kind=='berth_closure':
                assert any(resources.berth_closed[berth['id']])
                for a in run.assignments:
                    if a.berth_id==berth['id']:
                        assert not any(resources.berth_closed[berth['id']][i] for s in a.execution_profile['segments'] for i in range(s['start_slot'],s['end_slot']))
            if kind=='priority_arrival':
                assert db.get(m.VesselCall,calls[2]['id']).priority==1
                assert db.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==calls[2]['id'],m.VesselCallObservation.kind=='arrival'))
        assert api.get(prefix+'/dashboard',params={'run_id':result['new_run_id']}).status_code==200
    assert len(manager.events(demo['id']))==8 and digest(manager.engine)==before


def test_storm_detects_future_risk_and_recovery_replans_without_auto_approval(live_api):
    demo=start(live_api);event=inject(live_api,demo,'storm_crane_failure');r=event['result'];effect=r['event_effect']
    assert parse(effect['storm_start'])-parse(event['operational_time'])==timedelta(hours=6)
    assert r['changed_risks'] and r['plan_change_count']>0
    assert effect['crane_ids'] and r['metrics']['matched_baseline']=='post_event_fcfs'
    recovery=inject(live_api,demo,'storm_crane_recovery');new=recovery['result']
    assert new['plan_status']=='DRAFT' and not new['operational_plan_replaced']
    manager=live_api.app.state.live_demo
    with session_factory(manager.branch(demo['id']))() as db:
        state=snapshot_inputs(db,parse(recovery['operational_time']),['P04'])
        assert not any(d.get('id')==effect['advisory_id'] for d in state['disruptions'])
        assert not any(a['crane_id'] in effect['crane_ids'] and a['reason']=='breakdown' for a in state['availability'])


def test_clock_observations_are_reproducible_balanced_and_drafts_do_not_execute(live_api):
    demo=start(live_api);manager=live_api.app.state.live_demo;state=manager.get(demo['id']);engine=manager.branch(demo['id'])
    with session_factory(engine)() as db:
        until=parse(demo['clock'])+timedelta(hours=1)
        one=observe_tick(db,state,until);two=observe_tick(db,state,until)
        assert [c.model_dump() for c in one]==[c.model_dump() for c in two]
        carry={c.call_id for c in db.query(m.CarryInOperation).all()}
        assert {c.call_id for c in one if c.kind=='progress'}<=carry
        for yard in [c for c in one if c.kind=='yard']:
            assert yard.closing_teu==pytest.approx(yard.opening_teu+yard.inbound_teu-yard.outbound_teu)
            assert yard.closing_teu>=0


def test_approved_plan_frozen_assignments_survive_tick_and_need_explicit_replacement(live_api):
    api=live_api;demo=start(api);prefix='/api/v1/live-demo/'+demo['id'];manager=api.app.state.live_demo;engine=manager.branch(demo['id'])
    with session_factory(engine)() as db:base=db.get(m.OptimisationRun,demo['latest_run_id']);plan_id=base.plan.id
    reviewed=api.post(prefix+'/plans/'+plan_id+'/review',json={'expected_revision':1,'actor':'Supervisor'})
    assert reviewed.status_code==200,reviewed.text
    approved=api.post(prefix+'/plans/'+plan_id+'/approve',json={'expected_revision':2,'actor':'Supervisor'})
    assert approved.status_code==200,approved.text
    with session_factory(engine)() as db:
        original=db.get(m.SupervisorPlan,plan_id)
        assignments=SupervisorPlanService(db).assignments(original)
        frozen={a['call_id']:a for a in assignments if parse(a['start'])>=parse(demo['clock'])+timedelta(minutes=15) and parse(a['start'])<parse(demo['clock'])+timedelta(minutes=135)}
        ongoing={c.call_id:(c.berth_id,c.started_at,set(c.crane_ids)) for c in db.query(m.CarryInOperation).all()}
    assert frozen and ongoing  # neither preservation assertion may pass vacuously
    event=inject(api,demo,'clock_tick');result=event['result']
    assert result['frozen_assignment_count']==len(frozen)
    assert result['frozen_assignment_count']<len(assignments)
    with session_factory(engine)() as db:
        assert db.get(m.SupervisorPlan,plan_id).status=='APPROVED'
        after={a['call_id']:a for a in SupervisorPlanService(db).assignments(db.get(m.OptimisationRun,result['new_run_id']).plan)}
        for cid,a in frozen.items():assert (after[cid]['berth_id'],after[cid]['start'],after[cid]['end'],set(after[cid]['crane_ids']))==(a['berth_id'],a['start'],a['end'],set(a['crane_ids']))
        for c in db.query(m.CarryInOperation).all():
            if c.call_id in ongoing:assert (c.berth_id,c.started_at,set(c.crane_ids))==ongoing[c.call_id]
    assert api.post(prefix+'/plans/'+result['new_plan_id']+'/approve',json={'expected_revision':1,'actor':'Supervisor'}).status_code==409
    assert api.post(prefix+'/plans/'+result['new_plan_id']+'/review',json={'expected_revision':1,'actor':'Supervisor'}).status_code==200
    response=api.post(prefix+'/plans/'+result['new_plan_id']+'/approve',json={'expected_revision':2,'actor':'Supervisor'})
    assert response.status_code==200,response.text
    assert api.get(prefix+'/plans/'+plan_id).json()['status']=='SUPERSEDED'


def test_invalid_event_rolls_back_and_persisted_retry_is_idempotent(live_api):
    api=live_api;demo=start(api);manager=api.app.state.live_demo;engine=manager.branch(demo['id']);before=digest(engine)
    response=api.post('/api/v1/live-demo/'+demo['id']+'/events',json={'kind':'eta_delay','call_id':'NOT-A-CALL','expected_revision':1})
    assert response.status_code==202
    event=manager.events(demo['id'])[0];assert event.status=='FAILED' and not event.error['operational_changes_committed']
    assert digest(engine)==before and manager.get(demo['id']).clock==parse(demo['clock'])
    response=api.post('/api/v1/live-demo/'+demo['id']+'/events/'+event.id+'/retry',json={'actor':'Operator','expected_revision':2})
    assert response.status_code==202 and manager.events(demo['id'])[0].status=='FAILED'
    assert len(manager.events(demo['id']))==1 and digest(engine)==before
    assert api.post('/api/v1/live-demo/'+demo['id']+'/events',json={'kind':'clock_tick','expected_revision':1}).status_code==409


def test_sse_replays_durable_ids_and_honours_last_event_id(live_api):
    demo=start(live_api);event=inject(live_api,demo,'clock_tick');prefix='/api/v1/live-demo/'+demo['id']
    response=live_api.get(prefix+'/stream?once=true')
    assert response.status_code==200 and response.headers['content-type'].startswith('text/event-stream')
    cursor=f"{event['sequence']}.{event['stage_revision']}"
    assert f'id: {cursor}' in response.text and 'event: operation' in response.text and event['id'] in response.text
    assert 'event: operation' not in live_api.get(prefix+'/stream?once=true',headers={'Last-Event-ID':cursor}).text
    assert live_api.get(prefix+'/stream?once=true&after=invalid').status_code==422


def test_restart_recovers_committed_receipt_without_duplicate_operational_changes(live_api):
    demo=start(live_api);event=inject(live_api,demo,'clock_tick');manager=live_api.app.state.live_demo;engine=manager.branch(demo['id']);before=digest(engine)
    with manager.sessions.begin() as db:
        d=db.get(m.LiveDemoSession,demo['id']);d.status='PROCESSING';d.active_event_id=event['id']
        e=db.get(m.LiveDemoEvent,event['id']);e.status='OPTIMISING'
    manager.recover()
    assert manager.get(demo['id']).status=='READY' and manager.events(demo['id'])[0].status=='SUCCEEDED'
    assert digest(engine)==before


def test_unexpected_arrival_is_observed_now_and_cannot_be_delayed_afterwards(live_api):
    demo=start(live_api);manager=live_api.app.state.live_demo;engine=manager.branch(demo['id'])
    with session_factory(engine)() as db:
        data=snapshot_inputs(db,parse(demo['clock']),['P04'])
        call=next(c for c in data['calls'] if parse(c['scheduled_eta'])>parse(demo['clock'])+timedelta(hours=1) and parse(c['scheduled_eta'])<parse(demo['clock'])+timedelta(hours=40))
    event=inject(live_api,demo,'early_arrival',call_id=call['id'],hours=48)
    with session_factory(engine)() as db:
        actual=db.scalar(select(m.VesselCallObservation).where(m.VesselCallObservation.call_id==call['id'],m.VesselCallObservation.kind=='arrival'))
        assert actual.timestamp==event['operational_time'] and event['result']['event_effect']['actual_arrival']==actual.timestamp
    state=manager.get(demo['id']);queued=manager.enqueue(demo['id'],EventInput(kind='eta_delay',call_id=call['id'],hours=6,expected_revision=state.revision));manager.process(queued.id)
    assert manager.events(demo['id'])[0].status=='FAILED' and manager.events(demo['id'])[0].error['code']=='ARRIVAL_ALREADY_OBSERVED'


def test_unsafe_yard_reduction_is_rejected_and_current_reconciliation_is_visible(live_api):
    demo=start(live_api);manager=live_api.app.state.live_demo;engine=manager.branch(demo['id'])
    with session_factory(engine)() as db:
        data=snapshot_inputs(db,parse(demo['clock']),['P04'])
        tid=max(data['yards'],key=lambda y:y['closing_teu'])['terminal_id']
    event=manager.enqueue(demo['id'],EventInput(kind='yard_capacity_reduction',terminal_id=tid,capacity_pct=20,expected_revision=1));manager.process(event.id)
    assert manager.events(demo['id'])[0].status=='FAILED'
    assert manager.events(demo['id'])[0].error['code']=='UNSAFE_YARD_CAPACITY'
    result=inject(live_api,demo,'clock_tick')
    with session_factory(engine)() as db:
        data=snapshot_inputs(db,parse(result['operational_time']),['P04'])
        assert all(parse(y['timestamp'])==parse(result['operational_time']) for y in data['yards'])


@pytest.mark.skipif(not os.getenv('PORT_OPERATIONS_TEST_DATABASE_URL'),reason='Dedicated PostgreSQL test URL not configured')
def test_postgresql_source_is_copied_read_only_to_an_isolated_live_branch(source,trained,tmp_path,monkeypatch):
    monkeypatch.setenv('MODEL_DIRECTORY',str(trained[0].directory));monkeypatch.setenv('LIVE_DEMO_DIRECTORY',str(tmp_path/'branches'))
    schema='live_test_'+uuid4().hex;admin=make_engine(os.environ['PORT_OPERATIONS_TEST_DATABASE_URL'])
    engine=None;manager=None
    try:
        with admin.begin() as db:db.execute(CreateSchema(schema))
        url=make_url(os.environ['PORT_OPERATIONS_TEST_DATABASE_URL']).update_query_dict({'options':'-csearch_path='+schema})
        engine=make_engine(url);migrate(engine)
        with session_factory(engine).begin() as db:seed_tables(db,*source)
        before=digest(engine);manager=LiveDemoManager(engine)
        from app.live.schemas import StartInput
        demo=manager.start(StartInput(port_id='P04',time_limit_seconds=.5))
        event=manager.enqueue(demo.id,EventInput(kind='clock_tick',expected_revision=1));manager.process(event.id)
        assert manager.events(demo.id)[0].status=='SUCCEEDED'
        assert manager.branch(demo.id).dialect.name=='sqlite' and digest(engine)==before
    finally:
        if manager:manager.dispose()
        if engine:engine.dispose()
        with admin.begin() as db:db.execute(DropSchema(schema,cascade=True))
        admin.dispose()
