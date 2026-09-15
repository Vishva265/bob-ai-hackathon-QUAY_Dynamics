"""Metric accounting and ablation isolation have independent expected outcomes."""
import copy

import pytest
from pydantic import ValidationError

from app.evaluation.benchmark import EvaluationConfig, FixedCraneResources, measure, schedule_strategy, stability
from app.optimisation.inputs import prepare
from app.optimisation.resources import Resources, yard_trace
from test_optimisation import data as optimisation_data


def data(**kwargs):
    d=optimisation_data(**kwargs)
    for vessel in d['vessels']:vessel['capacity_teu']=10000
    d['overrides']=[]
    return d


def result_at_starts(d, starts, deferred=()):
    d=prepare(copy.deepcopy(d));r=Resources(d)
    options=[r.profile(d['calls'][i],'B0',s) for i,s in enumerate(starts)]
    return {'data':d,'options':options,'assignments':[r.public(o) for o in options],
        'deferred':list(deferred),'trace':yard_trace(r,options)[1],
        'info':{'solver_runtime_ms':0,'engine_runtime_ms':0,'solver_status':'TEST','schedule_source':'test'}}


def test_wait_percentiles_total_delay_and_strict_priority_sla():
    d=data(calls=2,moves=10)
    for c in d['calls']:c['priority']=1;c['scheduled_eta']=d['as_of']
    metrics=measure(result_at_starts(d,[8,32]),['A0','A1'],EvaluationConfig(priority_wait_sla_hours=2))
    assert metrics['average_wait_hours']==5
    assert metrics['p90_wait_hours']==pytest.approx(7.4)
    assert metrics['maximum_wait_hours']==8 and metrics['total_delay_hours']==10
    assert metrics['priority_sla_violations']==1


def test_deferred_calls_are_censored_not_zero_wait_or_silent_exclusions():
    d=data(calls=2,moves=10)
    for c in d['calls']:c['scheduled_eta']=d['as_of']
    metrics=measure(result_at_starts(d,[8],['A1']),['A0','A1'],EvaluationConfig())
    assert metrics['average_wait_hours']==2 and metrics['served_vessels']==1
    assert metrics['total_delay_hours']==122 and metrics['demand_average_wait_lower_bound_hours']==61
    assert metrics['delay_is_lower_bound'] and metrics['deferred_vessels']==1
    assert metrics['vessel_metrics'][1]['wait_is_lower_bound']
    assert metrics['estimated_cost_usd']>=172000


def test_cost_and_emissions_coefficients_can_be_scaled_without_moving_plan():
    d=data(calls=1,moves=10);d['calls'][0]['scheduled_eta']=d['as_of']
    r=result_at_starts(d,[8]);m=measure(r,['A0'],EvaluationConfig())
    scaled=copy.deepcopy(r)
    for key in ['waiting_cost_usd_per_hour','departure_delay_cost_usd_per_hour','crane_overtime_cost_usd_per_hour','deferral_cost_usd','waiting_co2_tonnes_per_hour']:
        scaled['data']['optimisation_policy'][key]*=1.25
    other=measure(scaled,['A0'],EvaluationConfig())
    assert other['estimated_cost_usd']==pytest.approx(m['estimated_cost_usd']*1.25)
    assert other['estimated_emissions_tonnes_co2']==pytest.approx(m['estimated_emissions_tonnes_co2']*1.25)


@pytest.mark.parametrize('strategy',['fcfs','berth_only','berth_crane','predictive_routing'])
def test_ablation_validates_and_never_mutates_input(strategy):
    d=data(calls=1,moves=100);d['calls'][0]['scheduled_eta']=d['as_of']
    original=copy.deepcopy(d);result=schedule_strategy(d,strategy,EvaluationConfig(repeats=1,solver_seconds=.1))
    assert d==original and result['cohort_ids']==['A0']
    assert result['assignments'] and measure(result,['A0'],EvaluationConfig())['validation_passed']
    if strategy in ('fcfs','berth_only'):
        assert all(len(s['crane_ids'])<=2 for a in result['assignments'] for s in a['execution_profile']['segments'])
    if strategy!='predictive_routing':assert result['data']['optimisation_policy']['weights']['prediction_risk']==0


def test_stability_detects_frozen_change_and_counts_eligible_changes():
    d=data(calls=1,moves=10)
    before=result_at_starts(d,[0]);after=copy.deepcopy(before)
    assert stability(before,after,120)['frozen_changed']==0
    after['assignments'][0]['berth_id']='DIFFERENT'
    with pytest.raises(AssertionError,match='Frozen'):stability(before,after,120)
    before=result_at_starts(d,[12]);after=copy.deepcopy(before);after['assignments'][0]['berth_id']='DIFFERENT'
    assert stability(before,after,120)['unchanged_eligible_fraction']==0


def test_announced_outage_is_applied_to_every_strategy():
    d=data(calls=1,moves=100)
    crane=d['cranes'][0]['id']
    d['overrides']=[{'kind':'crane_outage','crane_id':crane,'start':d['as_of'],'end':'2026-09-18T00:00:00Z'}]
    result=schedule_strategy(d,'fcfs',EvaluationConfig(repeats=1))
    assert all(crane not in s['crane_ids'] for a in result['assignments'] for s in a['execution_profile']['segments'])


def test_fixed_crane_ablation_restricts_new_work_and_preserves_actual_carry_bundle():
    d=data(calls=1,moves=1000)
    for i in [2,3]:d['cranes'].append(dict(d['cranes'][0],id=f'C0{i}'))
    fixed=FixedCraneResources(prepare(d));joint=Resources(prepare(d));call=d['calls'][0]
    one=fixed.profile(call,'B0',0);two=joint.profile(call,'B0',0)
    assert max(len(s['crane_ids']) for s in one['execution_profile']['segments'])==2
    assert max(len(s['crane_ids']) for s in two['execution_profile']['segments'])==4
    assert one['completion_slot']>two['completion_slot']
    carry={'call_id':'A0','berth_id':'B0','remaining_moves':1000,'crane_ids':['C00','C01','C02','C03']}
    observed=fixed.profile(call,'B0',0,carry=carry)
    assert max(len(s['crane_ids']) for s in observed['execution_profile']['segments'])==4


@pytest.mark.parametrize('options',[{'repeats':0},{'solver_seconds':20},{'priority_wait_sla_hours':-1},
    {'policy':{'allow_rerouting':True}},{'policy':{'replan_approved':True}}])
def test_invalid_experiment_configuration_is_rejected(options):
    with pytest.raises(ValidationError):EvaluationConfig(**options)


def publication():
    rows=[]
    for scenario in ['normal_operations','arrival_surge','storm_crane_breakdown']:
        for strategy in ['fcfs','berth_only','berth_crane','predictive_routing']:
            rows.append({'scenario_id':scenario,'strategy_id':strategy,'scenario':scenario,'strategy':strategy,
                'cohort_vessels':2,'served_vessels':1,'deferred_vessels':1,'average_wait_hours':2,
                'p90_wait_hours':2,'maximum_wait_hours':2,'total_delay_hours':122,
                'berth_utilisation':.2,'crane_utilisation':.2,'estimated_cost_savings_usd':0,
                'estimated_emissions_savings_tonnes_co2':0,'solver_runtime_ms':0,'validation_passed':True})
    return {'schema_version':'strategy-evaluation-v1','synthetic':True,'real_world_validated':False,
        'generated_at':'2026-09-13T00:00:00Z','model_version':'unit-test','rows':rows}


@pytest.mark.parametrize('defect',['unpaired','duplicate','real_claim','bad_counts','negative_wait'])
def test_publication_rejects_invalid_or_misleading_evidence(defect):
    from app.services.evaluation import EvaluationPublication
    p=publication()
    if defect=='unpaired':p['rows'][0]['cohort_vessels']=3;p['rows'][0]['deferred_vessels']=2
    if defect=='duplicate':p['rows'][1]=p['rows'][0]
    if defect=='real_claim':p['real_world_validated']=True
    if defect=='bad_counts':p['rows'][0]['served_vessels']=2
    if defect=='negative_wait':p['rows'][0]['average_wait_hours']=-1
    with pytest.raises(ValidationError):EvaluationPublication.model_validate(p)


def test_evaluation_api_missing_valid_and_corrupt_publication(tmp_path,monkeypatch):
    import json
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.main import create_app
    monkeypatch.setenv('EVALUATION_DIRECTORY',str(tmp_path))
    settings=replace(get_settings(),database_url='sqlite:///'+str(tmp_path/'api.db'))
    with TestClient(create_app(settings)) as api:
        assert api.get('/api/v1/evaluation/latest').status_code==404
        path=tmp_path/'summary.json';path.write_text(json.dumps(publication()))
        r=api.get('/api/v1/evaluation/latest');assert r.status_code==200 and len(r.json()['rows'])==12
        path.write_text('{bad');assert api.get('/api/v1/evaluation/latest').status_code==503
