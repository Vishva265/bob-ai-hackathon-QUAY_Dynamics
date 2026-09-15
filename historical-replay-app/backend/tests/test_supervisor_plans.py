import copy
import csv
import io
import json
from datetime import timedelta, datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import models as m
from app.plans.builder import build, material_changes
from app.plans.exports import csv_cell
from app.plans.schemas import ReplanInput
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, staging_moves
from app.optimisation.engine import fixed_options
from app.synthetic.simulator import parse, stamp
from app.services.context import snapshot_inputs
from test_operations_api import api, source, EPOCH
from test_optimisation import data, accepted, ORIGIN


def run_plan(api):
    response = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04'],
        'predictor': 'baseline', 'time_limit_seconds': 1})
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['status'] == 'succeeded', result['diagnostics']
    return api.get('/plans/72-hour', params={'port_id': 'P04'}).json()


def approve(api, plan):
    path = '/plans/'+plan['id']
    reviewed = api.post(path+'/review', json={'actor': 'reviewer', 'expected_revision': 1})
    assert reviewed.status_code == 200, reviewed.text
    approved = api.post(path+'/approve', json={'actor': 'supervisor', 'expected_revision': 2})
    assert approved.status_code == 200, approved.text
    return approved.json()


def effective(plan):
    return {a['call_id']: (a['berth_id'], a['start'], a['completion_time'], a['departure'])
            for shift in plan['shifts'] for a in shift['details']['berth_assignments']}


def test_nine_shift_publication_exports_and_state_transitions(api):
    reference=run_plan(api)
    with api.app.state.sessions.begin() as session:
        run=session.get(m.SupervisorPlan,reference['id']).run
        session.add(m.EarlyWarningRun(id=run.forecast_run_id,rules={},projection_method='test_observation',summaries=[],alert_counts={},assumptions=[]))
        session.flush()
        now=datetime.now(timezone.utc)
        session.add(m.CongestionAlert(id='KNOWN-ALERT',active_key='port:P04:LOW_CONFIDENCE',scope='port',scope_id='P04',
            port_id='P04',rule_code='LOW_CONFIDENCE',state='OPEN',revision=1,opened_at=now,updated_at=now,
            first_run_id=run.forecast_run_id,last_run_id=run.forecast_run_id,expected_start=EPOCH,
            expected_end='2026-09-16T00:00:00Z',duration_hours=72,evidence={'value':'LOW'}))
    plan = run_plan(api)
    assert plan['status'] == 'DRAFT' and plan['document']['shift_count'] == 9
    assert any(a.get('state')=='OPEN' and a.get('rule_code')=='LOW_CONFIDENCE'
               for s in plan['shifts'] for a in s['details']['congestion_alerts'])
    for shift in plan['shifts']:
        d = shift['details']
        assert parse(shift['end'])-parse(shift['start']) == timedelta(hours=8)
        assert d['required_supervisor_actions'] and d['contingency_actions'] and d['handover_notes']
        assert d['planned_container_moves'] == pytest.approx(sum(t['planned_moves'] for t in shift['tasks'] if t['task_type']=='container_handling'))
        for c in d['crane_allocation']:
            if c['crane_hours']:
                assert c['expected_moves_per_crane_hour'] == pytest.approx(c['planned_moves']/c['crane_hours'])
        assert all(y['peak_teu'] <= y['safe_planning_capacity_teu']+.02 for y in d['projected_yard_occupancy'])
    path = '/api/v1/plans/'+plan['id']
    assert api.post(path+'/approve', json={'actor':'supervisor','expected_revision':1}).status_code == 409
    json_export = api.get(path+'/export', params={'format':'json'})
    assert json_export.json() == plan
    csv_export = api.get(path+'/export', params={'format':'csv'})
    records = list(csv.DictReader(io.StringIO(csv_export.content.decode('utf-8-sig'))))
    assert sum(r['row_type']=='SHIFT_SUMMARY' for r in records) == 9
    assert {'CRANE_SEGMENT','YARD_PROJECTION','SUPERVISOR_ACTION','HANDOVER'} <= {r['row_type'] for r in records}
    printable = api.get(path+'/export', params={'format':'html'})
    assert printable.status_code == 200 and '@media print' in printable.text
    assert 'attachment;' in printable.headers['content-disposition']
    assert api.get(path+'/export', params={'format':'pdf'}).status_code == 422
    approved = approve(api, plan)
    assert approved['status']=='APPROVED' and approved['revision']==3
    assert approved['reviewed_by']=='reviewer' and approved['approved_by']=='supervisor'
    assert api.post(path+'/review',json={'actor':'reviewer','expected_revision':3}).status_code==409
    assert [e['to_state'] for e in api.get(path+'/history').json()['items']]==['DRAFT','REVIEWED','APPROVED']


def test_no_change_replanning_stability_and_supersession(api):
    old = approve(api, run_plan(api))
    revision = api.get('/plans/state').json()['operational_state_revision']
    response = api.post('/plans/'+old['id']+'/replan', json={'as_of':EPOCH,'expected_revision':3,
        'expected_state_revision':revision,'actor':'supervisor','predictor':'baseline','time_limit_seconds':1,'changes':[]})
    assert response.status_code==201, response.text
    assert response.json()['status']=='succeeded', response.json()['diagnostics']
    new = api.get('/plans/72-hour',params={'port_id':'P04'}).json()
    assert new['previous_plan_id']==old['id'] and new['status']=='DRAFT'
    assert effective(new)==effective(old)
    assert new['document']['changes_compared_with_approved_plan']==[]
    assert api.get('/plans/state').json()['operational_state_revision']==revision
    approve(api,new)
    superseded=api.get('/plans/'+old['id']).json()
    assert superseded['status']=='SUPERSEDED' and superseded['revision']==4
    assert api.get('/plans/'+old['id']+'/history').json()['items'][-1]['to_state']=='SUPERSEDED'
    assert effective(api.get('/plans/'+new['id']).json())==effective(old)


def test_complete_network_plan_supersedes_contained_single_port_approval(api):
    old = approve(api, run_plan(api))
    response = api.post('/optimisation/run', json={'as_of': EPOCH,
        'port_ids': ['P01', 'P02', 'P03', 'P04'], 'predictor': 'baseline',
        'time_limit_seconds': 1})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['status'] == 'succeeded', run['diagnostics']
    with api.app.state.sessions() as session:
        from app.services.supervisor_plans import SupervisorPlanService
        replacement = session.get(m.SupervisorPlan, run['plan']['id'])
        candidates = SupervisorPlanService(session).supersession_candidates(replacement)
        assert [candidate.id for candidate in candidates] == [old['id']]


def test_replan_requires_actual_progress_and_rolls_back_invalid_changes(api):
    plan=approve(api,run_plan(api))
    revision=api.get('/plans/state').json()['operational_state_revision']
    payload={'as_of':'2026-09-13T01:00:00Z','expected_revision':3,'expected_state_revision':revision,
        'actor':'supervisor','predictor':'baseline','time_limit_seconds':1,'changes':[]}
    response=api.post('/plans/'+plan['id']+'/replan',json=payload)
    assert response.status_code==409 and response.json()['error']['code']=='ACTUAL_PROGRESS_REQUIRED'
    assert api.get('/plans/state').json()['operational_state_revision']==revision
    payload['as_of']='2026-09-13T00:01:00Z'
    alignment=api.post('/plans/'+plan['id']+'/replan',json=payload)
    assert alignment.status_code==422 and alignment.json()['error']['code']=='REPLAN_GRID_ALIGNMENT'
    payload.update(as_of=EPOCH,changes=[{'kind':'eta','call_id':'MISSING','scheduled_eta':'2026-09-14T00:00:00Z'}])
    assert api.post('/plans/'+plan['id']+'/replan',json=payload).status_code==422
    assert api.get('/plans/state').json()['operational_state_revision']==revision
    with api.app.state.sessions() as session:
        assert not session.scalars(select(m.OperationalUpdateEvent)).all()


def test_observed_remaining_work_preserves_started_ownership_and_yard_flows():
    d=data(calls=1,moves=1000)
    old=accepted(d)
    new_origin=ORIGIN+timedelta(hours=1)
    d['as_of']=stamp(new_origin)
    d['commitments']=[dict(old,id='OLD')]
    d['carry_in']=[dict(call_id='A0',berth_id='B0',known_at=d['as_of'],started_at=stamp(ORIGIN),
        remaining_moves=800,remaining_unload_moves=800,remaining_load_moves=0,crane_ids=old['crane_ids'])]
    d['known_call_observations']=[dict(call_id='A0',kind='arrival',timestamp=stamp(ORIGIN))]
    prepared=prepare(d)
    assert prepared['commitments']==[] and prepared['confirmed_started_commitment_ids']==['OLD']
    r=Resources(prepared)
    fixed,_,errors=fixed_options(r)
    assert not errors and len(fixed)==1
    assert fixed[0]['berth_id']==old['berth_id'] and set(fixed[0]['crane_ids'])==set(old['crane_ids'])
    assert fixed[0]['planned_moves']==800
    assert staging_moves(r,fixed[0])==(1200,0)


def test_material_change_threshold_and_reasons():
    old=accepted(data(calls=1))
    new=copy.deepcopy(old)
    new['start']=stamp(parse(old['start'])+timedelta(minutes=15))
    assert material_changes([old],[new],['eta'],{})==[]
    new['start']=stamp(parse(old['start'])+timedelta(minutes=30))
    changes=material_changes([old],[new],['eta'],{})
    assert changes[0]['changed_fields']==['START_CHANGED']
    assert changes[0]['reason']['trigger_kinds']==['eta']


@pytest.mark.parametrize('change',[
    {'kind':'weather','port_id':'P04','timestamp':'2026-09-14T00:00:00Z','wind_mps':5,'rain_mm_per_hour':0,'visibility_m':1000},
    {'kind':'yard','terminal_id':'T','timestamp':EPOCH,'opening_teu':100,'closing_teu':120,'gate_outbound_teu':0,'inbound_teu':0,'outbound_teu':0,'queued_vessels':0},
    {'kind':'crane_availability','crane_id':'C','start':'2026-09-14T00:00:00Z','end':'2026-09-15T00:00:00Z','reason':'breakdown'},
])
def test_invalid_operational_observations(change):
    with pytest.raises(ValidationError):
        ReplanInput(as_of=EPOCH,expected_revision=1,expected_state_revision=1,actor='operator',changes=[change])


def test_csv_formula_safety():
    assert csv_cell('=HYPERLINK("evil")').startswith("'")
    assert csv_cell(-5)==-5


def test_eta_weather_yard_and_crane_updates_are_persisted_and_replanned(api):
    plan=approve(api,run_plan(api))
    state=api.get('/plans/state').json()['operational_state_revision']
    with api.app.state.sessions() as session:
        snapshot=snapshot_inputs(session,parse(EPOCH),['P04'])
    call=next(c for c in snapshot['calls'] if parse(c['scheduled_eta'])>parse(EPOCH)+timedelta(hours=8))
    yard=snapshot['yards'][0]
    changes=[dict(kind='eta',call_id=call['id'],scheduled_eta=stamp(parse(call['scheduled_eta'])+timedelta(hours=2))),
        dict(kind='weather',port_id='P04',timestamp=EPOCH,wind_mps=8,rain_mm_per_hour=1,visibility_m=10000),
        dict(kind='yard',terminal_id=yard['terminal_id'],timestamp=EPOCH,opening_teu=yard['closing_teu'],
            closing_teu=yard['closing_teu'],gate_outbound_teu=0,inbound_teu=0,outbound_teu=0,queued_vessels=0),
        dict(kind='crane_availability',crane_id=snapshot['cranes'][0]['id'],start=EPOCH,
            end='2026-09-13T02:00:00Z',reason='breakdown')]
    response=api.post('/plans/'+plan['id']+'/replan',json=dict(as_of=EPOCH,expected_revision=3,
        expected_state_revision=state,actor='operator',predictor='baseline',time_limit_seconds=1,changes=changes))
    assert response.status_code==201,response.text
    new=response.json()['plan']
    assert new and new['status']=='DRAFT' and new['document']['operational_changes']==changes
    assert api.get('/plans/state').json()['operational_state_revision']==state+1
    with api.app.state.sessions() as session:
        assert session.get(m.VesselCall,call['id']).scheduled_eta==changes[0]['scheduled_eta']
        assert session.scalars(select(m.OperationalUpdateEvent)).one().actor=='operator'
        # A predicted repair end is never treated as an observed restoration.
        later=snapshot_inputs(session,parse('2026-09-13T03:00:00Z'),['P04'])
        assert any(a['crane_id']==changes[3]['crane_id'] and a['start']==EPOCH for a in later['availability'])
        session.add(m.CraneRestorationObservation(id='RESTORED',crane_id=changes[3]['crane_id'],
            timestamp='2026-09-13T03:00:00Z',actor='operator'))
        session.flush()
        restored=snapshot_inputs(session,parse('2026-09-13T03:00:00Z'),['P04'])
        assert not any(a['crane_id']==changes[3]['crane_id'] and a['start']==EPOCH for a in restored['availability'])


def test_advanced_replan_measured_progress_requires_yard_and_pins_ownership(api):
    plan=approve(api,run_plan(api))
    origin=parse('2026-09-13T01:00:00Z')
    state=api.get('/plans/state').json()['operational_state_revision']
    with api.app.state.sessions() as session:
        snapshot=snapshot_inputs(session,origin,['P04'])
    operations={c['call_id']:c for c in snapshot['carry_in']}
    for a in snapshot['commitments']:
        if parse(a['start'])<origin:
            operations.setdefault(a['call_id'],dict(a,started_at=a['start'],remaining_moves=a['planned_moves']))
    calls={c['id']:c for c in snapshot['calls']}
    observations={(o['call_id'],o['kind']):o['timestamp'] for o in plan['document'].get('known_call_observations',[])}
    with api.app.state.sessions() as session:
        observations.update({(o.call_id,o.kind):o.timestamp for o in session.scalars(select(m.VesselCallObservation))})
    changes=[]
    for cid,operation in operations.items():
        call=calls[cid]
        remaining=int(operation['remaining_moves'])//2
        unload=min(call['unload_moves'],remaining)
        start=operation['started_at']
        changes.append(dict(kind='progress',call_id=cid,berth_id=operation['berth_id'],
            actual_arrival=observations.get((cid,'arrival'),stamp(min(parse(call['scheduled_eta']),parse(start)))),
            started_at=observations.get((cid,'berth_start'),start),observed_at=stamp(origin),
            completed_unload_moves=call['unload_moves']-unload,
            completed_load_moves=call['load_moves']-(remaining-unload),crane_ids=operation['crane_ids']))
    payload=dict(as_of=stamp(origin),expected_revision=3,expected_state_revision=state,actor='operator',
        predictor='baseline',time_limit_seconds=1,changes=changes)
    response=api.post('/plans/'+plan['id']+'/replan',json=payload)
    assert response.status_code==409 and response.json()['error']['code']=='YARD_OBSERVATION_REQUIRED',response.text
    assert api.get('/plans/state').json()['operational_state_revision']==state
    berths={b['id']:b for b in snapshot['berths']}
    affected={berths[c['berth_id']]['terminal_id'] for c in changes}
    for yard in snapshot['yards']:
        if yard['terminal_id'] in affected:
            changes.append(dict(kind='yard',terminal_id=yard['terminal_id'],timestamp=stamp(origin),
                opening_teu=yard['closing_teu'],closing_teu=yard['closing_teu'],gate_outbound_teu=0,
                inbound_teu=0,outbound_teu=0,queued_vessels=0))
    response=api.post('/plans/'+plan['id']+'/replan',json=payload)
    assert response.status_code==201,response.text
    new=response.json()['plan']
    assert new and new['status']=='DRAFT' and new['document']['as_of']==stamp(origin)
    for shift in new['shifts']:
        for a in shift['details']['berth_assignments']:
            if a['call_id'] in operations:
                assert a['berth_id']==operations[a['call_id']]['berth_id']
                assert a['original_started_at']==operations[a['call_id']]['started_at']
    with api.app.state.sessions() as session:
        for operation in session.scalars(select(m.CarryInOperation)):
            if operation.call_id in operations:
                old=operations[operation.call_id]
                assert set(operation.crane_ids)==set(old['crane_ids'])
                assert operation.remaining_moves==operation.remaining_load_moves+operation.remaining_unload_moves


def test_failed_started_operation_is_published_without_invented_completion():
    d=data(calls=1,moves=1000)
    d['weather'][0]['wind_mps']=35
    d['carry_in']=[dict(call_id='A0',berth_id='B0',known_at=d['as_of'],started_at=stamp(ORIGIN-timedelta(hours=1)),
        remaining_moves=800,remaining_unload_moves=800,remaining_load_moves=0,crane_ids=['C00','C01'])]
    shifts=[dict(shift_index=i,start=stamp(ORIGIN+timedelta(hours=8*i)),end=stamp(ORIGIN+timedelta(hours=8*(i+1))),tasks=[]) for i in range(9)]
    document,details=build(d,[],shifts,{},[],[])
    assert any(c['code']=='CARRY_IN_NO_COMPLETION' for c in document['unresolved_conflicts'])
    assert all(s['berth_assignments'][0]['completion_time'] is None for s in details)
    assert all(s['planned_container_moves']==0 for s in details)
    assert all(s['high_risk_handoffs'][0]['remaining_moves']==800 for s in details)
