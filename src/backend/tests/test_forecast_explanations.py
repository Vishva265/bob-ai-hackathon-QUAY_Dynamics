import copy
from types import SimpleNamespace

import pytest

from app.early_warning.rules import AlertRules
from app.schemas import ForecastExplanation
from app.services.forecast_explanations import explain_forecast


def example():
    row=dict(run_id='forecast-a', timestamp='2026-09-14T06:00:00Z', scope='terminal',
        terminal_id='T', berth_id=None, port_id='P', congestion_severity='HIGH', confidence_level='LOW',
        confidence_reasons=['Wide model event-error band', 'Persisted weather/yard assumptions exceed observation-age limit at target hour'],
        queue_length=1, average_wait_hours=19.2, congestion_probability=.079,
        main_causes=[dict(code='KNOWN_CRANE_DOWNTIME'),dict(code='WIND_OR_STORM_REDUCES_PRODUCTIVITY'),
                     dict(code='WAITING_TIME', evidence=dict(value=19.2, threshold=12, unit='hours'))])
    snapshot=dict(as_of='2026-09-13T00:00:00Z', overrides=[])
    inventory=dict(terminals=[dict(id='T',port_id='P')], berths=[dict(id='B',terminal_id='T')],
        cranes=[dict(id='C',berth_id='B')], yards=[dict(terminal_id='T',timestamp='2026-09-12T23:00:00Z',closing_teu=360)],
        weather=[dict(port_id='P',timestamp='2026-09-13T00:00:00Z',wind_mps=16,rain_mm_per_hour=0)],
        availability=[dict(crane_id='C',reason='maintenance',start='2026-09-14T00:00:00Z',end='2026-09-15T00:00:00Z')], disruptions=[])
    warning=SimpleNamespace(rules=AlertRules(waiting_hours=12).model_dump(),projection_method='fifo_quarter_hour_v1',assumptions=['Test-only persisted assumption'])
    plan=SimpleNamespace(status='APPROVED',document={'unresolved_conflicts':[]})
    return row,snapshot,inventory,warning,plan


def test_explanation_uses_recorded_thresholds_and_source_provenance_without_mutation():
    args=example()
    before=copy.deepcopy(args)
    result=ForecastExplanation.model_validate(explain_forecast(*args))
    assert '19.2h' in result.severity_explanation and '12h' in result.severity_explanation
    assert '8h' not in result.severity_explanation
    assert result.confidence_explanation.startswith('Confidence is LOW because the model event-error band is wide')
    assert '7.9' not in result.confidence_explanation
    assert result.inputs[0].source_type=='OBSERVED' and result.inputs[0].values['closing_teu']==360
    weather=next(s for s in result.inputs if s.kind=='weather')
    assert weather.source_type=='FORECAST_ASSUMPTION' and weather.freshness=='STALE'
    assert weather.age_hours==30
    crane=next(s for s in result.inputs if s.kind=='crane')
    assert crane.source_type=='SCHEDULED'
    assert result.supervisor_action=='Run rolling replan' and result.human_approval_required
    assert args==before


def test_scenario_weather_and_crane_overrides_are_never_labelled_observations():
    row,snapshot,inventory,warning,plan=example()
    storm=dict(kind='storm',port_id='P',start='2026-09-14T00:00:00Z',end='2026-09-15T00:00:00Z')
    snapshot['overrides']=[storm]
    inventory['disruptions']=[storm]
    inventory['availability'][0]['reason']='scenario_outage'
    result=explain_forecast(row,snapshot,inventory,warning,plan,scenario=True)
    assert next(s for s in result['inputs'] if s['kind']=='crane')['source_type']=='SCENARIO_OVERRIDE'
    assert next(s for s in result['inputs'] if s['kind']=='disruption')['source_type']=='SCENARIO_OVERRIDE'


def test_missing_provenance_does_not_invent_rules_or_input_windows():
    row,snapshot,inventory,_,plan=example()
    row['main_causes'][2]['evidence']={}
    inventory.update(yards=[],weather=[],availability=[])
    result=explain_forecast(row,snapshot,inventory,None,plan)
    assert result['triggered_thresholds']==[] and result['inputs']==[]
    assert result['missing_provenance'] and '8h' not in result['severity_explanation']
    assert 'crane downtime' in result['operator_interpretation'].lower()


@pytest.mark.parametrize('status,conflicts,scenario,expected',[
    ('REVIEWED',[],False,'Escalate for approval'),
    ('REVIEWED',[],True,'Run rolling replan'),
    ('REVIEWED',['unsafe'],False,'Run rolling replan'),
    ('APPROVED',[],False,'Run rolling replan')])
def test_action_respects_plan_state_conflicts_and_scenario(status,conflicts,scenario,expected):
    row,snapshot,inventory,warning,plan=example()
    plan.status=status;plan.document['unresolved_conflicts']=conflicts
    assert explain_forecast(row,snapshot,inventory,warning,plan,scenario)['supervisor_action']==expected


def test_breakdown_does_not_invent_recovery_and_future_failure_is_excluded():
    row,snapshot,inventory,warning,plan=example()
    inventory['availability']=[dict(crane_id='C',reason='breakdown',start='2026-09-12T20:00:00Z',end='2026-09-13T02:00:00Z')]
    result=explain_forecast(row,snapshot,inventory,warning,plan)
    crane=next(s for s in result['inputs'] if s['kind']=='crane')
    assert crane['source_type']=='OBSERVED' and crane['end'] is None
    assert 'unknown' in crane['assumptions'][0]
    inventory['availability'][0]['start']='2026-09-14T00:00:00Z'
    assert not any(s['kind']=='crane' for s in explain_forecast(row,snapshot,inventory,warning,plan)['inputs'])


def test_monitor_and_low_confidence_review_use_actual_stored_state():
    row,snapshot,inventory,warning,plan=example()
    row.update(congestion_severity='LOW',confidence_level='HIGH',confidence_reasons=[],main_causes=[],queue_length=0,average_wait_hours=0)
    inventory['availability']=[]
    assert explain_forecast(row,snapshot,inventory,warning,plan)['supervisor_action']=='Monitor'
    assert explain_forecast(row,snapshot,inventory,warning,plan)['human_approval_required'] is False
    row['confidence_level']='LOW';row['confidence_reasons']=['Wide model event-error band']
    assert explain_forecast(row,snapshot,inventory,warning,plan)['supervisor_action']=='Review before next shift'
