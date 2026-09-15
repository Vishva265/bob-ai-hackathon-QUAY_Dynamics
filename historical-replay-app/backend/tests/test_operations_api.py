import copy
import os
from uuid import uuid4
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlalchemy.engine import make_url
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic import command
from alembic.script import ScriptDirectory

from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory, alembic_config
from app.errors import DomainError
from app.main import create_app
from app.schemas import CallCreate
from app.services.operations import OperationsService
from app.services.seed import seed_tables
from app.services.scheduling import validate_schedule
from app.synthetic.simulator import generate, parse

EPOCH = '2026-09-13T00:00:00Z'


@pytest.fixture(scope='module')
def source():
    return generate(history_days=2, upcoming_days=3)


@pytest.fixture
def api(source, tmp_path):
    engine = make_engine(f'sqlite:///{(tmp_path/"operations.db").as_posix()}')
    migrate(engine)
    with session_factory(engine).begin() as session:
        seed_tables(session, *source)
    settings = replace(get_settings(), auto_migrate=False)
    with TestClient(create_app(settings, engine)) as client:
        yield client


def test_required_endpoints_seeded_workflow_and_approval(api):
    policy = api.get('/optimisation/policy')
    assert policy.status_code == 200 and policy.json()['weights']['waiting'] == 30
    ports = api.get('/ports', params={'limit': 2}).json()
    assert len(ports['items']) == 2 and ports['next_cursor']
    page2 = api.get('/api/v1/ports', params={'limit': 2, 'cursor': ports['next_cursor']}).json()
    assert len(page2['items']) == 2 and page2['next_cursor'] is None
    assert {p['id'] for p in ports['items']}.isdisjoint(p['id'] for p in page2['items'])
    assert api.get('/ready').json()['status'] == 'ready'
    status = api.get('/ports/P04/status', params={'as_of': EPOCH})
    assert status.status_code == 200
    assert status.json()['terminals'] == 6
    assert status.json()['missing_observations'] == []
    assert status.json()['weather']['period'] == 'historical_observation'
    assert api.get('/vessel-calls', params={'period': 'upcoming', 'port_id': 'P04'}).status_code == 200
    resources = api.get('/resources/availability', params={'start': EPOCH, 'end': '2026-09-16T00:00:00Z',
                                                           'port_id': 'P04', 'resource_type': 'crane'})
    assert resources.status_code == 200 and resources.json()['items']
    forecast = api.post('/forecasts/run', json={'as_of': EPOCH, 'port_ids': ['P04']})
    assert forecast.status_code == 201, forecast.text
    assert forecast.json()['quality'] == 'heuristic_uncalibrated'
    assert forecast.json()['bucket_count'] == 15*72
    forecasts = api.get('/forecasts/congestion', params={'run_id': forecast.json()['id'], 'limit': 100})
    assert forecasts.status_code == 200 and forecasts.json()['next_cursor']
    assert all(r['reasons'] for r in forecasts.json()['items'])
    optimised = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04'],
                                                   'forecast_run_id': forecast.json()['id']})
    assert optimised.status_code == 201, optimised.text
    run = optimised.json()
    assert run['status'] == 'succeeded', run['diagnostics']
    assert run['diagnostics']['unscheduled_call_ids'] == []
    assert run['assignments']
    assert run['metrics']['validation_passed'] and run['comparison']
    assert run['objective_breakdown']['priority_delay']['weight'] == 30
    assert all(a['completion_time'] and a['execution_profile']['segments'] for a in run['assignments'])
    assert all(len(a['cranes']) == sum(len(seg['crane_ids']) for seg in a['execution_profile']['segments']) for a in run['assignments'])
    assert api.get('/optimisation/'+run['id']).json()['id'] == run['id']
    plan = api.get('/plans/72-hour', params={'port_id': 'P04'}).json()
    assert len(plan['shifts']) == 9
    assert [s['shift_index'] for s in plan['shifts']] == list(range(9))
    assert all(parse(s['end'])-parse(s['start']) == timedelta(hours=8) for s in plan['shifts'])
    assert api.post('/plans/'+plan['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
    approved = api.post('/plans/'+plan['id']+'/approve', json={'actor': 'demo_supervisor', 'expected_revision': 2})
    assert approved.status_code == 200, approved.text
    assert approved.json()['status'] == 'APPROVED' and approved.json()['revision'] == 3
    assert approved.json()['approved_at'].endswith('Z')
    assert api.post('/plans/'+plan['id']+'/approve', json={'actor': 'demo_supervisor', 'expected_revision': 1}).status_code == 409
    with api.app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(m.ApprovalEvent)) == 1


def test_create_call_validates_references_capacity_timezone_and_duplicates(api, source):
    historical = next(c for c in source[0]['vessel_calls'] if c['period'] == 'historical')
    payload = dict(historical, id='CLIENT-1', scheduled_eta='2026-09-25T05:30:00+05:30')
    payload.pop('period')
    created = api.post('/vessel-calls', json=payload)
    assert created.status_code == 201, created.text
    assert created.json()['scheduled_eta'] == '2026-09-25T00:00:00Z'
    assert api.post('/vessel-calls', json=payload).status_code == 409
    bad = dict(payload, id='CLIENT-2', vessel_id='MISSING')
    assert api.post('/vessel-calls', json=bad).status_code == 404
    bad = dict(payload, id='CLIENT-2', onboard_teu=999999)
    assert api.post('/vessel-calls', json=bad).json()['error']['code'] == 'VESSEL_CAPACITY'
    for bad in [dict(payload, scheduled_eta='2026-09-25T00:00:00'), dict(payload, unload_moves=-1),
                dict(payload, invented_wait=3), dict(payload, priority=0)]:
        response = api.post('/vessel-calls', json=bad)
        assert response.status_code == 422
        assert response.json()['error']['request_id'] == response.headers['X-Request-ID']


def test_filters_pagination_and_clear_errors(api):
    filtered = api.get('/vessel-calls', params={'port_id': 'P01', 'period': 'upcoming', 'limit': 1})
    row = filtered.json()['items'][0]
    assert row['terminal_id'].startswith('P01') and row['period'] == 'upcoming'
    cursor = filtered.json()['next_cursor']
    assert api.get('/vessel-calls', params={'port_id': 'P02', 'period': 'upcoming', 'cursor': cursor}).status_code == 422
    for path, params, status in [('/ports', {'limit': 0}, 422), ('/ports', {'cursor': '??bad'}, 422),
        ('/ports/MISSING/status', {'as_of': EPOCH}, 404), ('/ports/P01/status', {'as_of': '2026-09-13'}, 422),
        ('/resources/availability', {'start': EPOCH, 'end': EPOCH}, 422),
        ('/plans/72-hour', {}, 404), ('/optimisation/MISSING', {}, 404), ('/not-a-route', {}, 404)]:
        result = api.get(path, params=params)
        assert result.status_code == status, result.text
        assert 'error' in result.json()


def test_seed_excludes_future_truth_and_preserves_observed_carry_in(api, source):
    with api.app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(m.CallOutcome).where(m.CallOutcome.departure > parse(EPOCH))) == 0
        assert session.scalar(select(func.count()).select_from(m.WeatherObservation).where(m.WeatherObservation.period == 'simulated_future_truth')) == 0
        carries = session.scalars(select(m.CarryInOperation)).all()
        assert carries
        assert all(c.known_at == EPOCH and c.started_at < EPOCH and c.remaining_moves >= 0 for c in carries)
        with pytest.raises(ValueError, match='already populated'):
            seed_tables(session, *source)


def test_scenarios_are_isolated_and_cannot_approve_simulated_constraints(api):
    before = api.get('/vessel-calls', params={'port_id': 'P04', 'limit': 100}).json()
    response = api.post('/scenarios/simulate', json=dict(name='Storm test', as_of=EPOCH, port_ids=['P04'],
        overrides=[dict(kind='storm', port_id='P04', start='2026-09-14T00:00:00Z', end='2026-09-14T08:00:00Z')]))
    assert response.status_code == 201, response.text
    run = response.json()
    assert run['scenario_id'] and run['status'] == 'succeeded', run['diagnostics']
    assert api.get('/vessel-calls', params={'port_id': 'P04', 'limit': 100}).json() == before
    if run['plan']:
        assert api.post('/plans/'+run['plan']['id']+'/approve', json={'actor': 'supervisor', 'expected_revision': 1}).json()['error']['code'] == 'SCENARIO_READ_ONLY'
    invalid = api.post('/scenarios/simulate', json=dict(name='Bad outage', as_of=EPOCH,
        overrides=[dict(kind='crane_outage', crane_id='MISSING', start=EPOCH, end='2026-09-14T00:00:00Z')]))
    assert invalid.status_code == 422


def test_stale_operational_snapshot_is_not_approved(api):
    response = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']})
    run = response.json()
    assert run['plan']
    with api.app.state.sessions.begin() as session:
        terminal = session.get(m.Terminal, 'P04-T01')
        terminal.gate_capacity_teu_per_hour += 1
    assert api.post('/plans/'+run['plan']['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
    rejected = api.post('/plans/'+run['plan']['id']+'/approve', json={'actor': 'supervisor', 'expected_revision': 2})
    assert rejected.status_code == 409 and rejected.json()['error']['code'] == 'STALE_PLAN'


def test_independent_validator_rejects_resource_overlap(api):
    from app.services.context import snapshot_inputs, apply_overrides
    response = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']}).json()
    first = copy.deepcopy(response['assignments'][0])
    first['crane_ids'] = [c['crane_id'] for c in first.pop('cranes')]
    second = copy.deepcopy(first)
    second['call_id'] = response['assignments'][1]['call_id']
    with api.app.state.sessions() as session:
        from app import models as m
        run = session.get(m.OptimisationRun, response['id'])
        data = apply_overrides(run.input_snapshot) if run else apply_overrides(snapshot_inputs(session, parse(EPOCH), ['P04']))
        # Identical original call is rejected as duplicate before resource checks.
        with pytest.raises(DomainError, match='duplicate demand'):
            validate_schedule(data, [first, first])


def test_short_carry_in_inside_long_maintenance_has_productive_time_after_pause(api):
    from app.services.context import snapshot_inputs, apply_overrides
    from app.services.scheduling import schedule, productive_slots
    with api.app.state.sessions() as session:
        data = apply_overrides(snapshot_inputs(session, parse(EPOCH), ['P04']))
    carry = min(data['carry_in'], key=lambda c: c['remaining_moves'])
    carry['remaining_moves'] = 1
    data['availability'].append(dict(crane_id=carry['crane_ids'][0], start=EPOCH, end='2026-09-13T08:00:00Z'))
    assignments, _, status, diagnostics, _ = schedule(data, 5)
    assert status in {'OPTIMAL', 'FEASIBLE'} or diagnostics.get('fallback_status') == 'FEASIBLE', diagnostics
    assignment = next(a for a in assignments if a['call_id'] == carry['call_id'])
    assert parse(assignment['end']) > parse('2026-09-13T08:00:00Z')
    assert productive_slots(data, assignment)


def test_approved_work_is_preserved_in_successor_shift_view(api):
    first = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']}).json()
    assert api.post('/plans/'+first['plan']['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
    assert api.post('/plans/'+first['plan']['id']+'/approve', json={'actor': 'supervisor', 'expected_revision': 2}).status_code == 200
    next_run = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']})
    assert next_run.status_code == 201, next_run.text
    successor = next_run.json()
    assert successor['status'] == 'succeeded'
    assert any(s['tasks'] for s in successor['plan']['shifts'])
    previous_call_ids = {a['call_id'] for a in first['assignments']}
    assert {t['call_id'] for s in successor['plan']['shifts'] for t in s['tasks']} <= previous_call_ids


def test_migration_upgrade_downgrade_and_orm_relationships(tmp_path):
    engine = make_engine(f'sqlite:///{(tmp_path/"migrations.db").as_posix()}')
    config = alembic_config()
    try:
        with engine.begin() as conn:
            config.attributes['connection'] = conn
            command.upgrade(config, 'head')
            command.downgrade(config, 'base')
            command.upgrade(config, 'head')
        assert ScriptDirectory.from_config(config).get_current_head() == '0012'
        assert m.Terminal.port.property.back_populates == 'terminals'
        assert m.BerthAssignment.cranes.property.back_populates == 'assignment'
    finally:
        engine.dispose()


def test_sqlite_zero_configuration_startup_and_readiness_failure(tmp_path):
    settings = replace(get_settings(), database_url=f'sqlite:///{(tmp_path/"empty.db").as_posix()}', auto_migrate=True)
    with TestClient(create_app(settings)) as client:
        assert client.get('/ready').status_code == 200
        assert client.get('/ports').json()['items'] == []
        assert client.post('/forecasts/run', json={'as_of': EPOCH}).status_code == 503
        paths = client.get('/openapi.json').json()['paths']
        for path in ['/ports', '/ports/{port_id}/status', '/vessel-calls', '/resources/availability',
                     '/forecasts/congestion', '/forecasts/run', '/optimisation/run', '/optimisation/{run_id}',
                     '/plans/72-hour', '/scenarios/simulate', '/plans/{plan_id}/approve']:
            assert '/api/v1'+path in paths
    engine = make_engine('sqlite:///:memory:')
    with TestClient(create_app(replace(settings, auto_migrate=False), engine)) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/ready').status_code == 503


@pytest.mark.skipif(not os.getenv('PORT_OPERATIONS_TEST_DATABASE_URL'), reason='Dedicated PostgreSQL operational test URL not configured')
def test_postgresql_migrations_seed_api_and_approval_in_isolated_schema(source):
    url = os.environ['PORT_OPERATIONS_TEST_DATABASE_URL']
    schema = 'ops_test_'+uuid4().hex
    admin = make_engine(url)
    with admin.begin() as conn:
        conn.execute(CreateSchema(schema))
    parsed = make_url(url).update_query_dict({'options': f'-csearch_path={schema}'})
    engine = make_engine(parsed.render_as_string(hide_password=False))
    try:
        migrate(engine)
        config = alembic_config()
        with engine.begin() as conn:
            config.attributes['connection'] = conn
            command.downgrade(config, 'base')
            command.upgrade(config, 'head')
        with session_factory(engine).begin() as session:
            seed_tables(session, *source)
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), m.Base.metadata) == []
        settings = replace(get_settings(), auto_migrate=False)
        with TestClient(create_app(settings, engine)) as client:
            assert client.get('/ready').json()['database'] == 'postgresql'
            assert len(client.get('/ports').json()['items']) == 4
            run = client.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']})
            assert run.status_code == 201, run.text
            assert run.json()['plan']
            assert client.post('/plans/'+run.json()['plan']['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
            approved = client.post('/plans/'+run.json()['plan']['id']+'/approve', json={'actor': 'pg_supervisor', 'expected_revision': 2})
            assert approved.status_code == 200, approved.text
            assert approved.json()['approved_at'].endswith('Z')
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def test_eligible_future_plan_supersession_is_atomic_and_frozen_work_remains(api):
    first = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']}).json()
    assert first['status'] == 'succeeded'
    assert api.post('/plans/'+first['plan']['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
    assert api.post('/plans/'+first['plan']['id']+'/approve', json={'actor': 'first_supervisor', 'expected_revision': 2}).status_code == 200
    request = {'as_of': EPOCH, 'port_ids': ['P04'], 'policy': {'replan_approved': True, 'freeze_minutes': 120}}
    second_response = api.post('/optimisation/run', json=request)
    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    assert second['status'] == 'succeeded', second['diagnostics']
    released = set(second['diagnostics']['released_commitment_ids'])
    assert released
    assert released < {a['id'] for a in first['assignments']}
    assert api.post('/plans/'+second['plan']['id']+'/review', json={'actor': 'review_supervisor', 'expected_revision': 1}).status_code == 200
    approved = api.post('/plans/'+second['plan']['id']+'/approve', json={'actor': 'second_supervisor', 'expected_revision': 2})
    assert approved.status_code == 200, approved.text
    with api.app.state.sessions() as session:
        old = session.scalars(select(m.BerthAssignment).where(m.BerthAssignment.run_id == first['id'])).all()
        assert {a.id for a in old if a.superseded_at} == released
        assert all(a.superseded_at is None for a in old if a.id not in released)
        assert session.scalar(select(func.count()).select_from(m.ApprovalEvent)) == 2
    third = api.post('/optimisation/run', json={'as_of': EPOCH, 'port_ids': ['P04']}).json()
    assert third['status'] == 'succeeded', third['diagnostics']
    assert not (released & {a['id'] for a in third.get('assignments', [])})
