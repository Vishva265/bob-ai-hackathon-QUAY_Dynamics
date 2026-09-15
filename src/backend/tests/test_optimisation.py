import copy
import math
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.errors import DomainError
from app.optimisation.config import OptimisationPolicy
from app.optimisation.engine import candidate_berths, schedule
from app.optimisation.resources import Resources
from app.optimisation.metrics import call_terms
from app.optimisation.validation import validate_schedule
from app.synthetic.simulator import stamp
from test_early_warning import tiny_data, ORIGIN


def data(calls=2, moves=100):
    d = tiny_data(calls, moves)[0]
    d['as_of'] = stamp(ORIGIN)
    d['terminals'][0]['gate_capacity_teu_per_hour'] = 200
    d['known_call_observations'] = []
    d['optimisation_policy'] = OptimisationPolicy().model_dump()
    return d


def accepted(d, index=0, bid='B0', start=0):
    r = Resources(d)
    return r.public(r.profile(d['calls'][index], bid, start))


def test_independent_berth_overlap():
    d = data()
    with pytest.raises(DomainError) as fail:
        validate_schedule(d, [accepted(d, 0), accepted(d, 1)])
    assert fail.value.code == 'RESOURCE_OVERLAP'


@pytest.mark.parametrize('field,value', [('length_m', 20), ('depth_m', 2), ('equipment', 'incompatible')])
def test_incompatible_assignments(field, value):
    d = data()
    a = accepted(d)
    if field == 'equipment':
        d['vessels'][0]['required_equipment'] = 'super_post_panamax_sts'
    d['berths'][0][field] = value
    with pytest.raises(DomainError) as fail:
        validate_schedule(d, [a])
    assert fail.value.code == 'INCOMPATIBLE_ASSIGNMENT'


def test_unavailable_cranes_and_zero_cranes():
    d = data()
    a = accepted(d)
    d['availability'].append(dict(crane_id=a['crane_ids'][0], start=d['as_of'], end=stamp(ORIGIN+timedelta(hours=120)), reason='maintenance'))
    with pytest.raises(DomainError) as fail:
        validate_schedule(d, [a])
    assert fail.value.code == 'CRANE_UNAVAILABLE'
    d = data(calls=1)
    d['cranes'] = []
    assignments, recommendations, status, diagnostics, _ = schedule(d, 1)
    assert assignments == [] and diagnostics['unscheduled_call_ids'] == ['A0']
    assert recommendations[0]['kind'] == 'deferral'


def test_yard_hard_capacity_prevents_unsafe_staging():
    d = data(calls=1)
    d['yards'][0]['closing_teu'] = 9000
    d['terminals'][0]['gate_capacity_teu_per_hour'] = 0
    a = accepted(d)
    with pytest.raises(DomainError) as fail:
        validate_schedule(d, [a])
    assert fail.value.code == 'YARD_CAPACITY'
    assignments, _, _, diagnostics, _ = schedule(d, 2)
    assert assignments == [] and diagnostics['metrics']['yard_peak_occupancy'] <= .9
    assert diagnostics['unscheduled_call_ids'] == ['A0']


def test_priority_one_is_highest_and_objective_has_all_components():
    d = data()
    d['berths'] = d['berths'][:1]
    d['cranes'] = [c for c in d['cranes'] if c['berth_id'] == 'B0']
    d['calls'][0]['priority'] = 5
    d['calls'][1]['priority'] = 1
    assignments, _, status, diagnostics, runtime = schedule(d, 3)
    assert len(assignments) == 2, diagnostics
    by_id = {a['call_id']: a for a in assignments}
    assert by_id['A1']['start'] < by_id['A0']['start']
    assert diagnostics['metrics']['validation_passed']
    assert set(diagnostics['objective_breakdown']) == set(OptimisationPolicy().weights.model_dump())
    assert diagnostics['metrics']['objective_total'] == pytest.approx(sum(v['weighted'] for v in diagnostics['objective_breakdown'].values()))
    assert diagnostics['solver_runtime_ms'] <= 3300
    validate_schedule(d, assignments, [], diagnostics['gate_plan'])


def test_strict_infeasible_has_explanation_and_never_publishes_invalid_fallback():
    d = data(calls=1)
    d['optimisation_policy']['allow_deferral'] = False
    for b in d['berths']:
        b['depth_m'] = 1
    assignments, _, status, diagnostics, _ = schedule(d, 2)
    assert status == 'INFEASIBLE' and assignments == []
    assert diagnostics['schedule_source'] == 'no_feasible_schedule'
    assert diagnostics['infeasibility_explanations'] and diagnostics['infeasibility_core_call_ids']


def test_no_cp_solution_uses_validated_greedy_fallback(monkeypatch):
    import app.optimisation.engine as engine
    monkeypatch.setattr(engine, 'solve', lambda *args: (None, None, None, dict(solver_status='UNKNOWN', solver_runtime_ms=1)))
    d = data()
    assignments, _, status, diagnostics, _ = engine.schedule(d, .1)
    assert status == 'UNKNOWN' and diagnostics['schedule_source'] == 'greedy_fallback'
    assert len(assignments) == 2 and diagnostics['fallback_status'] == 'FEASIBLE'
    validate_schedule(d, assignments, [], diagnostics['gate_plan'])


def test_tide_windows_use_past_observations_and_delay_entry():
    d = data(calls=1)
    d['vessels'][0]['draft_m'] = 10
    for berth in d['berths']:
        berth['depth_m'] = 11.8
    d['tide_observations'] = [dict(port_id='P', timestamp=stamp(ORIGIN+timedelta(hours=h)),
        height_m=1.1*math.sin(2*math.pi*h/12.42-math.pi/2)) for h in range(-72, 0)]
    r = Resources(d)
    assert r.profile(d['calls'][0], 'B0', 0) is None
    assert r.profile(d['calls'][0], 'B0', 8) is not None
    future = copy.deepcopy(d)
    future['tide_observations'].append(dict(port_id='P', timestamp=stamp(ORIGIN+timedelta(hours=1)), height_m=50))
    assert Resources(future).tides == r.tides


def test_objective_weight_validation_and_safety_precedence():
    with pytest.raises(ValidationError):
        OptimisationPolicy(weights=dict(waiting=-1))
    with pytest.raises(ValidationError):
        OptimisationPolicy(berth_exit_buffer_minutes=0)
    with pytest.raises(ValidationError):
        OptimisationPolicy(waiting_co2_tonnes_per_hour=1e300)
    d = data()
    a = accepted(d)
    a['completion_time'] = a['start']
    with pytest.raises(DomainError) as fail:
        validate_schedule(d, [a])
    assert fail.value.code == 'INVALID_ASSIGNMENT'


def test_forecast_severity_and_tail_fairness_have_distinct_objective_terms():
    d=data(calls=1);call=d['calls'][0]
    d['prediction_risk']={'A0':dict(prediction=32,lower=24,upper=40,model_version='test-v2')}
    r=Resources(d)
    late=r.profile(call,'B0',120)
    terms=call_terms(r,late)
    assert terms['prediction_risk']>terms['waiting']
    assert terms['fairness_delay']>0
    d['prediction_risk']={}
    assert call_terms(Resources(d),Resources(d).profile(call,'B0',120))['prediction_risk']==0


def test_optional_routing_checks_transit_and_destination_resources():
    d = data(calls=1)
    d['optimisation_policy']['allow_rerouting'] = True
    for b in d['berths']:
        b['depth_m'] = 2
    d['port_ids'].append('Q')
    d['routing_ports'] = [dict(id='P', latitude=0, longitude=0), dict(id='Q', latitude=.1, longitude=0)]
    d['terminals'].append(dict(id='T2', port_id='Q', yard_capacity_teu=10000, gate_capacity_teu_per_hour=200))
    d['berths'].append(dict(id='B2', terminal_id='T2', length_m=200, depth_m=14, under_keel_clearance_m=1,
                           equipment='panamax_sts', max_cranes=4))
    d['cranes'].append(dict(id='C2', berth_id='B2', equipment='panamax_sts', productivity_moves_per_hour=100))
    d['cargo'].append(dict(berth_id='B2', cargo_type='general'))
    d['yards'].append(dict(terminal_id='T2', closing_teu=900, timestamp=stamp(ORIGIN-timedelta(hours=1))))
    d['weather'].append(dict(port_id='Q', timestamp=d['as_of'], wind_mps=0, rain_mm_per_hour=0, visibility_m=10000))
    assignments, recommendations, status, diagnostics, _ = schedule(d, 2)
    assert len(assignments) == 1 and assignments[0]['berth_id'] == 'B2', diagnostics
    assert assignments[0]['start'] > d['as_of']
    route = next(r for r in recommendations if r['kind'] == 'alternate_port')
    assert route['alternate_port_id'] == 'Q' and diagnostics['metrics']['rerouted_vessels'] == 1
    validate_schedule(d, assignments, [], diagnostics['gate_plan'])


def test_approved_route_is_the_only_destination_considered_by_joint_replan():
    d=data(calls=2)
    d['optimisation_policy']['allow_rerouting']=True
    d['approved_routing_terminal_ids']={'A0':'T2'}
    d['port_ids'].append('Q')
    d['routing_ports']=[dict(id='P',latitude=0,longitude=0),dict(id='Q',latitude=.05,longitude=0)]
    d['terminals'].append(dict(id='T2',port_id='Q',yard_capacity_teu=10000,gate_capacity_teu_per_hour=200))
    d['berths'].append(dict(id='B2',terminal_id='T2',length_m=200,depth_m=14,under_keel_clearance_m=1,equipment='panamax_sts',max_cranes=4))
    d['cranes'].append(dict(id='C2',berth_id='B2',equipment='panamax_sts',productivity_moves_per_hour=100))
    d['cargo'].append(dict(berth_id='B2',cargo_type='general'))
    d['yards'].append(dict(terminal_id='T2',closing_teu=900,timestamp=stamp(ORIGIN-timedelta(hours=1))))
    d['weather'].append(dict(port_id='Q',timestamp=d['as_of'],wind_mps=0,rain_mm_per_hour=0,visibility_m=10000))
    resources=Resources(d)
    assert candidate_berths(resources,resources.calls['A0'])==['B2']
    assert all(resources.terminals[resources.berths[bid]['terminal_id']]['port_id']=='P'
               for bid in candidate_berths(resources,resources.calls['A1']))
    assignments,_,_,diagnostics,_=schedule(d,1)
    assert next(a for a in assignments if a['call_id']=='A0')['berth_id']=='B2'
    assert diagnostics['metrics']['rerouted_vessels']==1


def test_future_replanning_respects_freeze_and_has_reassignment_penalty():
    from app.optimisation.inputs import prepare
    from app.optimisation.metrics import call_terms
    d = data()
    old = accepted(d, 0, 'B0', 16)
    old['id'] = 'OLD'
    frozen = accepted(d, 1, 'B1', 4)
    frozen['id'] = 'FROZEN'
    d['commitments'] = [old, frozen]
    d['optimisation_policy']['replan_approved'] = True
    prepared = prepare(d)
    assert prepared['released_commitment_ids'] == ['OLD']
    assert prepared['commitments'] == [frozen]
    r = Resources(prepared)
    reassigned = r.profile(d['calls'][0], 'B1', 32)
    assert call_terms(r, reassigned)['reassignment'] > 0


def test_wait_metrics_include_known_accrued_wait_and_show_additional_wait():
    from app.optimisation.metrics import report
    d = data(calls=1)
    d['known_call_observations'] = [dict(call_id='A0', kind='arrival', timestamp=stamp(ORIGIN-timedelta(hours=3)))]
    r = Resources(d)
    option = r.profile(d['calls'][0], 'B0', 0)
    metrics, _, _, _ = report(r, [option], [])
    assert metrics['average_wait_hours'] == 3 and metrics['average_additional_wait_hours'] == 0
    assert r.public(option)['waiting_minutes'] == 180
    d['availability'] = [dict(crane_id=c['id'], start=d['as_of'], end=stamp(ORIGIN+timedelta(hours=12)), reason='maintenance') for c in d['cranes']]
    d['disruptions'].append(dict(kind='storm', port_id='P', terminal_id=None,
        start=d['as_of'], end=stamp(ORIGIN+timedelta(hours=12)), value=20))
    assignments, recommendations, _, diagnostics, _ = schedule(d, 1)
    assert len(assignments) == 1 and diagnostics['metrics']['average_additional_wait_hours'] >= 12
    assert not any(row['kind'] == 'delayed_arrival' for row in recommendations)


def test_frozen_approved_work_cannot_ignore_known_outage():
    d = data(calls=1)
    old = accepted(d)
    old['id'] = 'APPROVED'
    d['commitments'] = [old]
    d['availability'].append(dict(crane_id=old['crane_ids'][0], start=d['as_of'],
        end=stamp(ORIGIN+timedelta(hours=120)), reason='maintenance'))
    assignments, _, status, diagnostics, _ = schedule(d, 1)
    assert status == 'INFEASIBLE' and not assignments
    assert diagnostics['schedule_source'] == 'no_feasible_schedule'
    assert any(e['code'] == 'FIXED_CALENDAR_CONFLICT' for e in diagnostics['infeasibility_explanations'])


def test_invalid_cp_incumbent_uses_independently_validated_fallback(monkeypatch):
    import app.optimisation.engine as engine
    original = engine.solve
    def corrupt(*args):
        selected, deferred, gates, info = original(*args)
        selected = copy.deepcopy(selected)
        selected[0]['execution_profile']['segments'][0]['moves'] += 100000
        return selected, deferred, gates, info
    monkeypatch.setattr(engine, 'solve', corrupt)
    d = data()
    assignments, _, status, diagnostics, _ = schedule(d, 2)
    assert diagnostics['schedule_source'] == 'greedy_fallback'
    assert any(e['code'] == 'INSUFFICIENT_PROCESSING_CAPACITY' for e in diagnostics['infeasibility_explanations'])
    validate_schedule(d, assignments, [], diagnostics['gate_plan'])
