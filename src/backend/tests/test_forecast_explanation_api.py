from app import models as m
from app.synthetic.simulator import parse
from test_operations_api import api,source,EPOCH


def test_dashboard_explanation_is_typed_and_does_not_change_forecast_or_plan(api):
    run=api.post('/optimisation/run',json={'as_of':EPOCH,'port_ids':['P04'],'predictor':'baseline','time_limit_seconds':1}).json()
    with api.app.state.sessions.begin() as session:
        stored=session.get(m.OptimisationRun,run['id'])
        tid=stored.input_snapshot['terminals'][0]['id']
        fid=stored.forecast_run_id
        session.add(m.EarlyWarningRun(id=fid,rules={'enabled':['WAITING_TIME'],'waiting_hours':12,'maximum_observation_age_hours':6},
            projection_method='fifo_quarter_hour_v1',summaries=[],alert_counts={},assumptions=['Persisted integration test assumption']))
        session.flush()
        session.add(m.OperationalForecast(id='explanation-test',run_id=fid,scope='terminal',scope_id=tid,port_id='P04',
            terminal_id=tid,berth_id=None,timestamp=parse(EPOCH),berth_utilisation=1/3,queue_length=1,average_wait_hours=19.2,
            yard_occupancy=.36,crane_utilisation=.364,congestion_probability=.079,probability_lower=0,probability_upper=.7,
            probability_basis='trained_scope_model',congestion_severity='HIGH',confidence_level='LOW',
            confidence_reasons=['Wide model event-error band'],main_causes=[dict(code='WAITING_TIME',message='average_wait_hours exceeds configured threshold',evidence=dict(value=19.2,threshold=12,unit='hours'))],
            arrival_workload_ratio=1,arrival_workload_increase_moves=0,is_hotspot=1,first_expected_hotspot_time=None,
            expected_hotspot_duration_hours=0,model_version='test-only',prediction_timestamp=parse(EPOCH)))
    before=api.get('/optimisation/'+run['id']).json()
    from app.services.dashboard import DashboardService,DashboardOut
    with api.app.state.sessions() as session:
        DashboardOut.model_validate(DashboardService(session).output(run['id']))
    value=api.get('/dashboard',params={'run_id':run['id']})
    assert value.status_code==200,value.text
    row=value.json()['forecast_rows'][0]
    assert row['average_wait_hours']==19.2 and row['congestion_probability']==.079
    assert '12h' in row['explanation']['severity_explanation']
    assert row['explanation']['forecast_run_id']==fid and row['explanation']['inputs']
    assert api.get('/optimisation/'+run['id']).json()==before
