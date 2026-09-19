from datetime import timedelta

import yaml

from app import models as m
from app.synthetic.simulator import parse, stamp
from test_copilot import run, snapshot, offline_explanations
from test_operations_api import api, source


def request(run):
    assignment=next(row for row in run['assignments'] if row['cranes'])
    return dict(run_id=run['id'],crane_id=assignment['cranes'][0]['crane_id'],
                start_utc=assignment['start'],duration_hours=8,time_limit_seconds=.1)


def test_incident_commander_is_unsaved_grounded_and_comparative(api,run):
    before_state=snapshot(api)
    response=api.post('/api/v1/copilot/incidents/assess',json=request(run))
    assert response.status_code==200,response.text
    result=response.json()
    assert result['source_run_id']==run['id'] and result['source_plan_id']==run['plan']['id']
    assert result['persisted'] is False and result['plan_modified'] is False
    assert result['incident']['kind']=='crane_outage'
    assert result['incident']['crane_id']==request(run)['crane_id']
    assert result['risk_level'] in ('LOW','MEDIUM','HIGH','CRITICAL')
    assert result['affected_call_count']==len(result['affected_calls'])
    assert all(row['status'] in ('NEWLY_DEFERRED','NEWLY_SERVED','RESCHEDULED')
               for row in result['affected_calls'])
    assert all(1<=shift<=9 for shift in result['impacted_shifts'])
    assert {row['id'] for row in result['evidence']}=={'E1','E2','E3','E4','E5','E6'}
    assert result['suggested_action']['human_approval_required']
    assert result['suggested_action']['executable'] is False
    for key,value in result['delta'].items():
        assert value==round(result['after'][key]-result['before'][key],6)
    if result['comparison_available']:
        assert result['after'] and 'Validated' in result['comparison_note']
    else:
        assert result['after']=={} and result['delta']=={}
        assert result['evidence'][1]['value']=='unavailable'
        assert 'unavailable' in result['comparison_note']
    assert snapshot(api)==before_state


def test_incident_commander_rejects_bad_scope_and_time(api,run):
    body=request(run)
    unknown=api.post('/api/v1/copilot/incidents/assess',json=dict(body,crane_id='NOT-A-CRANE'))
    assert unknown.status_code==404 and unknown.json()['error']['code']=='INCIDENT_CRANE_NOT_FOUND'
    too_early=stamp(parse(run['as_of'])-timedelta(minutes=1))
    outside=api.post('/api/v1/copilot/incidents/assess',json=dict(body,start_utc=too_early))
    assert outside.status_code==422 and outside.json()['error']['code']=='INCIDENT_OUTSIDE_HORIZON'


def test_incident_commander_rejects_scenario_source(api,run):
    with api.app.state.sessions.begin() as session:
        source_run=session.get(m.OptimisationRun,run['id'])
        scenario=m.Scenario(id='INCIDENT-SCENARIO',name='Existing hypothetical',
                            as_of=source_run.as_of,overrides=[],created_at=source_run.created_at)
        session.add(scenario)
        source_run.scenario_id=scenario.id
    response=api.post('/api/v1/copilot/incidents/assess',json=request(run))
    assert response.status_code==409
    assert response.json()['error']['code']=='INCIDENT_SOURCE_SCENARIO'


def test_bob_incident_mode_is_restricted_to_read_and_mcp():
    path=__import__('pathlib').Path(__file__).resolve().parents[3]/'.bob'/'custom_modes.yaml'
    mode=yaml.safe_load(path.read_text(encoding='utf-8'))['customModes'][0]
    assert mode['slug']=='quay-incident-commander'
    assert mode['groups']==['read','mcp']
    assert 'assess_operational_incident' in mode['customInstructions']
