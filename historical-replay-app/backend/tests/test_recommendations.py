import copy
import os
from uuid import uuid4
from datetime import timedelta
from dataclasses import replace

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.main import create_app
from app.optimisation.resources import Resources
from app.recommendations.engine import RecommendationEngine, impact
from app.recommendations.schemas import RecommendationPolicy, VoyageInput, TerminalTariff, RecommendationInput
from app.schemas import OptimisationInput
from app.services.planning import PlanningService
from app.services.seed import seed_tables
from app.synthetic.simulator import generate, stamp
from test_optimisation import data
from test_early_warning import ORIGIN


def fixture():
    d = data(calls=1, moves=1000)
    d['routing_ports'] = [dict(id='P', latitude=10, longitude=70), dict(id='Q', latitude=10.1, longitude=70)]
    d['port_ids'].append('Q')
    d['terminals'] += [dict(d['terminals'][0], id='T2'), dict(d['terminals'][0], id='TQ', port_id='Q')]
    for tid, bid in [('T2', 'B2'), ('TQ', 'BQ')]:
        d['berths'].append(dict(d['berths'][0], id=bid, terminal_id=tid))
        d['cranes'] += [dict(c, id=bid+'C'+str(i), berth_id=bid) for i, c in enumerate(d['cranes'][:2])]
        d['cargo'].append(dict(berth_id=bid, cargo_type='general'))
        d['yards'].append(dict(d['yards'][0], terminal_id=tid))
    d['weather'].append(dict(d['weather'][0], port_id='Q'))
    d['calls'][0]['scheduled_eta'] = stamp(ORIGIN+timedelta(hours=12))
    d['prediction_risk'] = {'A0': dict(prediction=40, lower=39, upper=41, model_version='test-v1')}
    r = Resources(d)
    baseline = [r.public(r.profile(d['calls'][0], 'B0', 208))]
    voyage = VoyageInput(call_id='A0', position_as_of=ORIGIN, remaining_distance_nm=216,
        eta_uncertainty_hours=0, customer_deadline=ORIGIN+timedelta(hours=100), source_label='Test confirmed voyage')
    tariffs = [TerminalTariff(terminal_id=t['id'], port_call_usd=1000, handling_usd_per_move=50,
        inland_usd_per_teu=10, inland_hours=6, inland_uncertainty_hours=0,
        inland_co2_tonnes_per_teu=.001, cargo_booking_confirmed=True, source_label='Test common customer route') for t in d['terminals']]
    policy = RecommendationPolicy(uncertainty_fallback_hours=1)
    return d, baseline, voyage, tariffs, policy


def engine(d=None, baseline=None, voyage=None, tariffs=None, policy=None):
    defaults = fixture()
    d, baseline, voyage, tariffs, policy = [x if x is not None else defaults[i] for i, x in enumerate((d, baseline, voyage, tariffs, policy))]
    return RecommendationEngine(d, baseline, policy, [voyage], tariffs, 'test-v1')


def option(result, action, terminal=None):
    return next(o for o in result['options'] if o['action'] == action and (terminal is None or o['terminal_id'] == terminal))


def test_real_nearby_compatible_port_can_pass_end_to_end_gate_and_reproducible():
    e = engine()
    a = e.evaluate('A0')
    b = e.evaluate('A0')
    assert a == b
    o = option(a, 'ALTERNATE_PORT')
    assert o['feasible'] and o['eligible']
    assert o['outcome']['diversion_distance_nm'] == pytest.approx(6.004046, abs=.001)
    assert o['expected_hours_saved'] > 30 and o['estimated_net_benefit_usd'] > 1000
    assert a['operator_approval_required'] and a['independent_what_if']
    assert len(a['main_reasons']) == 3 and not a['operationally_actionable']


def test_same_port_terminal_and_earlier_arrival_options_are_evaluated():
    result = engine().evaluate('A0')
    assert {o['action'] for o in result['options']} == {'KEEP_CURRENT_PLAN', 'SLOW_STEAM_OR_DELAY_ARRIVAL', 'EARLIER_ARRIVAL', 'ALTERNATE_TERMINAL', 'ALTERNATE_PORT'}
    assert option(result, 'ALTERNATE_TERMINAL')['eligible']
    early = option(result, 'EARLIER_ARRIVAL')
    assert early['outcome']['arrival'] < result['current_plan_outcome']['arrival']
    assert early['outcome']['speed_knots'] == 22


def test_distant_diversion_rejected_even_with_severe_delay_and_free_capacity():
    d, b, v, t, p = fixture()
    d['routing_ports'][1].update(latitude=-33, longitude=150)
    o = option(engine(d=d).evaluate('A0'), 'ALTERNATE_PORT')
    assert not o['eligible'] and o['outcome'] is None
    assert 'DIVERSION_DISTANCE_EXCEEDS_NEARBY_PORT_LIMIT' in o['rejection_codes']
    assert o['evidence']['diversion_distance_nm'] > 4000


@pytest.mark.parametrize('failure', ['draft', 'length', 'equipment', 'cargo', 'cranes', 'storm', 'yard', 'berth'])
def test_hard_incompatibility_or_unavailable_capacity_rejects(failure):
    d, baseline, voyage, tariffs, p = fixture()
    b = next(b for b in d['berths'] if b['id'] == 'BQ')
    if failure == 'draft':
        b['depth_m'] = 3
    elif failure == 'length':
        b['length_m'] = 20
    elif failure == 'equipment':
        b['equipment'] = 'incompatible'
    elif failure == 'cargo':
        d['cargo'] = [c for c in d['cargo'] if c['berth_id'] != 'BQ']
    elif failure == 'cranes':
        d['availability'] += [dict(crane_id=c['id'], start=stamp(ORIGIN), end=stamp(ORIGIN+timedelta(hours=120)), reason='maintenance') for c in d['cranes'] if c['berth_id'] == 'BQ']
    elif failure == 'storm':
        d['disruptions'].append(dict(kind='storm', port_id='Q', start=stamp(ORIGIN), end=stamp(ORIGIN+timedelta(hours=120))))
    elif failure == 'yard':
        next(y for y in d['yards'] if y['terminal_id'] == 'TQ')['closing_teu'] = 9000
        next(t for t in d['terminals'] if t['id'] == 'TQ')['gate_capacity_teu_per_hour'] = 0
    else:
        # A full-horizon frozen reservation leaves no receiving berth time.
        d['calls'].append(dict(d['calls'][0], id='BLOCK', terminal_id='TQ', scheduled_eta=stamp(ORIGIN)))
        d['commitments'].append(dict(id='BLOCK-ASSIGN', call_id='BLOCK', berth_id='BQ', start=stamp(ORIGIN),
            end=stamp(ORIGIN+timedelta(hours=120)), completion_time=stamp(ORIGIN+timedelta(hours=119)),
            planned_moves=1, crane_ids=['BQC0'], waiting_minutes=0, execution_profile=None))
    result = engine(d, baseline, voyage, tariffs, p).evaluate('A0')
    o = option(result, 'ALTERNATE_PORT')
    assert not o['eligible'] and 'NO_COMPATIBLE_RECEIVING_CAPACITY' in o['rejection_codes']


@pytest.mark.parametrize('failure,code', [('tariff', 'MISSING_RECEIVING_TARIFF_AND_INLAND_ROUTE'), ('booking', 'RECEIVING_CARGO_BOOKING_UNCONFIRMED')])
def test_unknown_commercial_inputs_are_not_invented(failure, code):
    d, b, v, t, p = fixture()
    if failure == 'tariff':
        t = [x for x in t if x.terminal_id != 'TQ']
    else:
        t[-1] = t[-1].model_copy(update={'cargo_booking_confirmed': False})
    assert code in option(engine(d, b, v, t, p).evaluate('A0'), 'ALTERNATE_PORT')['rejection_codes']


def test_expensive_inland_route_and_uncertainty_can_veto_congestion_diversion():
    d, b, v, t, p = fixture()
    t[-1] = t[-1].model_copy(update={'inland_usd_per_teu': 1000})
    o = option(engine(d, b, v, t, p).evaluate('A0'), 'ALTERNATE_PORT')
    assert o['feasible'] and not o['eligible']
    assert 'INSUFFICIENT_END_TO_END_BENEFIT' in o['rejection_codes']
    d['prediction_risk']['A0'].update(lower=0, upper=100)
    o = option(engine(d=d).evaluate('A0'), 'ALTERNATE_PORT')
    assert 'UNCERTAINTY_ERASES_DIVERSION_BENEFIT' in o['rejection_codes']


def test_delivery_deadline_and_inland_delay_are_end_to_end():
    d, b, v, t, p = fixture()
    t[-1] = t[-1].model_copy(update={'inland_hours': 100})
    o = option(engine(d, b, v, t, p).evaluate('A0'), 'ALTERNATE_PORT')
    assert 'CUSTOMER_DEADLINE_RISK_INCREASES' in o['rejection_codes']
    assert o['expected_hours_saved'] < 0


def test_strict_benefit_boundary_and_slow_steaming_cannot_invent_hours_saved():
    _, _, _, _, p = fixture()
    current = dict(expected_delivery=stamp(ORIGIN+timedelta(hours=20)), total_cost_usd=5000,
        total_co2_tonnes=10, uncertainty_hours=0, deadline_lateness_hours=0, deadline_worst_lateness_hours=0)
    alternative = dict(current, total_cost_usd=4000)
    _, codes = impact(current, alternative, p, 'SLOW_STEAM_OR_DELAY_ARRIVAL')
    assert 'INSUFFICIENT_END_TO_END_BENEFIT' in codes
    alternative['total_cost_usd'] -= .01
    delta, codes = impact(current, alternative, p, 'SLOW_STEAM_OR_DELAY_ARRIVAL')
    assert codes == [] and delta['expected_hours_saved'] == 0
    delta, codes = impact(current, alternative, p, 'ALTERNATE_PORT')
    assert 'INSUFFICIENT_DELIVERY_TIME_SAVING' in codes


def test_slow_steaming_retains_physical_reservation_and_reduces_fuel_without_delivery_gain():
    d, baseline, voyage, tariffs, p = fixture()
    original = copy.deepcopy(d)
    result = engine(d, baseline, voyage, tariffs, p).evaluate('A0')
    slow = option(result, 'SLOW_STEAM_OR_DELAY_ARRIVAL')
    assert slow['feasible'] and slow['eligible']
    assert slow['expected_hours_saved'] == 0
    assert slow['estimated_cost_change_usd'] < 0 and slow['estimated_emissions_change_tonnes'] < 0
    assert slow['outcome']['berth_start'] == baseline[0]['start']
    assert slow['outcome']['departure'] == baseline[0]['end']
    assert slow['outcome']['planned_wait_hours'] < result['current_plan_outcome']['planned_wait_hours']
    assert d == original


def test_stale_or_inconsistent_navigation_inputs_block_all_changes():
    d, b, v, t, p = fixture()
    for update, code in [(dict(position_as_of=ORIGIN-timedelta(hours=5)), 'STALE_VESSEL_POSITION'),
                         (dict(remaining_distance_nm=1000), 'VOYAGE_INPUTS_CONTRADICT_ETA')]:
        result = engine(d, b, v.model_copy(update=update), t, p).evaluate('A0')
        assert result['recommended_action'] == 'KEEP_CURRENT_PLAN'
        assert all(code in o['rejection_codes'] for o in result['options'][1:])


def test_recent_position_speed_change_affects_only_untravelled_distance_and_physical_lower_band():
    d, b, v, t, p = fixture()
    v = v.model_copy(update={'position_as_of': ORIGIN-timedelta(hours=2)})
    e = engine(d, b, v, t, p)
    result = e.evaluate('A0')
    early = option(result, 'EARLIER_ARRIVAL')['outcome']
    remaining = 216-2*18
    expected_arrival = ORIGIN+timedelta(hours=12-(remaining/18-remaining/22))
    assert early['arrival'] == stamp(expected_arrival)
    assert early['sailing_hours'] == pytest.approx(remaining/22, abs=1e-6)
    for o in result['options']:
        if o['outcome']:
            assert o['outcome']['delivery_lower'] >= o['outcome']['arrival']


def test_observed_arrival_is_never_adjusted_or_rerouted():
    d, b, v, t, p = fixture()
    d['known_call_observations'].append(dict(call_id='A0', kind='arrival', timestamp=stamp(ORIGIN)))
    result = engine(d, b, v, t, p).evaluate('A0')
    assert result['recommended_action'] == 'KEEP_CURRENT_PLAN'
    assert all(not o['eligible'] for o in result['options'][1:])
    assert result['current_plan_outcome']['sailing_hours'] == 0
    assert result['current_plan_outcome']['cost_breakdown']['sailing_fuel'] == 0


def test_missing_baseline_never_fabricates_delivery_or_savings():
    d, _, v, t, p = fixture()
    result = RecommendationEngine(d, [], p, [v], t, 'test-v1').evaluate('A0')
    assert result['current_plan_outcome'] is None and result['expected_hours_saved'] is None
    assert all(not o['eligible'] for o in result['options'][1:])


@pytest.mark.parametrize('values', [dict(remaining_distance_nm=-1), dict(maximum_speed_knots=10), dict(position_as_of='2026-09-13T00:00:00'), dict(eta_uncertainty_hours=float('nan'))])
def test_voyage_validation(values):
    _, _, v, _, _ = fixture()
    with pytest.raises(ValidationError):
        VoyageInput.model_validate(dict(v.model_dump(), **values))


def test_request_duplicate_inputs_rejected():
    _, _, v, t, _ = fixture()
    with pytest.raises(ValidationError):
        RecommendationInput(source_run_id='run', voyages=[v, v], tariffs=t)


@pytest.fixture(params=['sqlite', pytest.param('postgresql', marks=pytest.mark.skipif(
    not os.getenv('PORT_OPERATIONS_TEST_DATABASE_URL'), reason='Dedicated PostgreSQL test URL not configured'))])
def recommendation_db(request, tmp_path):
    if request.param == 'sqlite':
        engine = make_engine(f'sqlite:///{(tmp_path/"recommend.db").as_posix()}')
        try:
            yield engine
        finally:
            engine.dispose()
        return
    url = os.environ['PORT_OPERATIONS_TEST_DATABASE_URL']
    admin = make_engine(url)
    schema = 'recommend_test_'+uuid4().hex
    with admin.begin() as conn:
        conn.execute(CreateSchema(schema))
    engine = make_engine(make_url(url).update_query_dict({'options': '-csearch_path='+schema}).render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_api_persistence_pagination_validation_and_no_operational_mutation(recommendation_db):
    db = recommendation_db
    migrate(db)
    with session_factory(db).begin() as session:
        seed_tables(session, *generate(history_days=2, upcoming_days=3))
        source = PlanningService(session).run(OptimisationInput(as_of=ORIGIN, port_ids=['P04'], predictor='baseline', time_limit_seconds=1))
        source_id, call_id = source.id, source.input_snapshot['calls'][0]['id']
        initial_calls = session.scalar(select(func.count()).select_from(m.VesselCall))
        initial_assignments = session.scalar(select(func.count()).select_from(m.BerthAssignment))
        initial_revision = session.get(m.PlanningState, 1).revision
    with TestClient(create_app(replace(get_settings(), auto_migrate=False), db)) as client:
        assert client.get('/recommendations/policy').status_code == 200
        response = client.post('/recommendations/what-if', json=dict(source_run_id=source_id, call_id=call_id))
        assert response.status_code == 201, response.text
        result = response.json()
        assert result['recommendations'][0]['recommended_action'] == 'KEEP_CURRENT_PLAN'
        assert result['recommendations'][0]['current_plan_outcome'] is None
        assert result['recommendations'][0]['is_expired']
        assert client.get('/api/v1/recommendations/runs/'+result['id']).json() == result
        second = client.post('/recommendations/what-if', json=dict(source_run_id=source_id, call_id=call_id))
        assert second.status_code == 201
        first_page = client.get('/recommendations', params=dict(limit=1, call_id=call_id)).json()
        assert first_page['next_cursor']
        next_page = client.get('/recommendations', params=dict(limit=1, call_id=call_id, cursor=first_page['next_cursor'])).json()
        assert next_page['items'][0]['id'] != first_page['items'][0]['id']
        assert client.get('/recommendations', params=dict(limit=1, action='EARLIER_ARRIVAL', cursor=first_page['next_cursor'])).status_code == 422
        assert client.post('/recommendations/what-if', json=dict(source_run_id=source_id, call_id='MISSING')).status_code == 422
        assert client.post('/recommendations/run', json=dict(source_run_id='MISSING')).status_code == 404
        assert client.post('/recommendations/run', json=dict(source_run_id=source_id, policy={'maximum_diversion_nm': -1})).status_code == 422
        assert client.get('/openapi.json').json()['paths']['/api/v1/recommendations/what-if']
        with session_factory(db).begin() as session:
            assert session.scalar(select(func.count()).select_from(m.VesselCall)) == initial_calls
            assert session.scalar(select(func.count()).select_from(m.BerthAssignment)) == initial_assignments
            assert session.get(m.PlanningState, 1).revision == initial_revision
            assert session.scalar(select(func.count()).select_from(m.RecommendationDecision)) == 2
            session.get(m.PlanningState, 1).revision += 1
        assert client.get('/recommendations/runs/'+result['id']).json()['source_state_changed']
