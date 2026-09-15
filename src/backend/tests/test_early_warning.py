import copy
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, func

from app import models as m
from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.early_warning.projection import project
from app.early_warning.rules import AlertRules, evaluate, hotspot_windows
from app.errors import DomainError
from app.main import create_app
from app.repositories.alerts import AlertRepository
from app.schemas import EarlyWarningInput
from app.services.early_warning import EarlyWarningService
from app.services.seed import seed_tables
from app.synthetic.simulator import parse, stamp
from test_predictive import trained, source

ORIGIN = parse('2026-09-13T00:00:00Z')


def neutral():
    return dict(berth_utilisation=.85, yard_occupancy=.90, average_wait_hours=8,
        crane_utilisation=.95, arrival_workload_ratio=1.5, arrival_workload_increase_moves=500,
        confidence_level='MEDIUM', confidence_reasons=[])


@pytest.mark.parametrize('field,code', [('berth_utilisation', 'BERTH_UTILISATION'),
    ('yard_occupancy', 'YARD_OCCUPANCY'), ('average_wait_hours', 'WAITING_TIME'), ('crane_utilisation', 'CRANE_UTILISATION')])
def test_strict_threshold_boundaries(field, code):
    row = neutral()
    assert evaluate(row, AlertRules()) == []
    row[field] -= 1e-7
    assert evaluate(row, AlertRules()) == []
    row[field] += 2e-7
    assert [r['code'] for r in evaluate(row, AlertRules())] == [code]


def test_surge_requires_relative_and_absolute_increase_and_confidence_is_separate():
    row = neutral()
    row['arrival_workload_ratio'] += .01
    assert evaluate(row, AlertRules()) == []
    row['arrival_workload_increase_moves'] += .01
    assert [r['code'] for r in evaluate(row, AlertRules())] == ['ARRIVAL_SURGE']
    row['confidence_level'] = 'LOW'
    assert {r['code'] for r in evaluate(row, AlertRules())} == {'ARRIVAL_SURGE', 'LOW_CONFIDENCE'}
    assert evaluate(row, AlertRules(enabled=[])) == []


@pytest.mark.parametrize('values', [dict(berth_utilisation=1.1), dict(waiting_hours=-1),
    dict(crane_utilisation=float('nan')), dict(enabled=['UNSUPPORTED']), dict(enabled=['LOW_CONFIDENCE'] * 2),
    dict(arrival_window_hours=0), dict(unknown=True)])
def test_configuration_validation(values):
    with pytest.raises((ValidationError, ValueError)):
        AlertRules(**values)


def tiny_data(calls=6, moves=100):
    data = dict(port_ids=['P'], terminals=[dict(id='T', port_id='P', yard_capacity_teu=10000)],
        berths=[dict(id=f'B{i}', terminal_id='T', length_m=200, depth_m=14, under_keel_clearance_m=1,
                    equipment='panamax_sts', max_cranes=4) for i in range(2)],
        cranes=[dict(id=f'C{i}{j}', berth_id=f'B{i}', equipment='panamax_sts', productivity_moves_per_hour=50) for i in range(2) for j in range(2)],
        vessels=[dict(id='V', length_m=150, draft_m=7, required_equipment='panamax_sts', max_cranes=4)],
        calls=[dict(id=f'A{i}', vessel_id='V', terminal_id='T', scheduled_eta=stamp(ORIGIN), priority=3,
                    cargo_type='general', unload_moves=moves, load_moves=0, teu_per_move=1.5) for i in range(calls)],
        cargo=[dict(berth_id=f'B{i}', cargo_type='general') for i in range(2)],
        yards=[dict(terminal_id='T', closing_teu=900, timestamp=stamp(ORIGIN-timedelta(hours=1)))],
        weather=[dict(port_id='P', timestamp=stamp(ORIGIN), wind_mps=0, rain_mm_per_hour=0)],
        availability=[], disruptions=[], carry_in=[], commitments=[])
    predictions = {(scope, sid, ORIGIN+timedelta(hours=h)): dict(prediction=.1, lower=0, upper=.2,
        level='LOW', model_version='test-v1', factors=[], prediction_timestamp=stamp(ORIGIN))
        for scope, sid in [('port', 'P'), ('terminal', 'T')] for h in range(72)}
    waiting = {c['id']: dict(prediction=0) for c in data['calls']}
    return data, predictions, waiting


def projection(data, predictions, waiting, **rules):
    return project(data, predictions, waiting, [], {'T': 0}, AlertRules(**rules), ORIGIN)


def test_projection_queue_conservation_compatibility_capacity_and_causal_volume():
    data, predictions, waiting = tiny_data()
    rows, summaries = projection(data, predictions, waiting)
    assert len(rows) == 4*72
    for hour in range(72):
        selected = [r for r in rows if r['timestamp'] == ORIGIN+timedelta(hours=hour)]
        terminal = next(r for r in selected if r['scope'] == 'terminal')
        assert sum(r['queue_length'] for r in selected if r['scope'] == 'berth') == pytest.approx(terminal['queue_length'])
    assert all(0 <= r[k] <= 1 for r in rows for k in ['berth_utilisation', 'crane_utilisation', 'yard_occupancy'])
    assert all(r['confidence_level'] == 'LOW' and r['probability_basis'] == 'terminal_model_prior' for r in rows if r['scope'] == 'berth')
    doubled = copy.deepcopy(data)
    for call in doubled['calls']:
        call['unload_moves'] *= 2
    larger, _ = projection(doubled, predictions, waiting)
    assert sum(r['queue_length'] for r in larger if r['scope'] == 'terminal') > sum(r['queue_length'] for r in rows if r['scope'] == 'terminal')
    shallow = copy.deepcopy(data)
    for berth in shallow['berths']:
        berth['depth_m'] = 2
    rejected, _ = projection(shallow, predictions, waiting)
    assert all(r['berth_utilisation'] == 0 for r in rejected)
    assert any(c['code'] == 'NO_COMPATIBLE_BERTH' for r in rejected for c in r['main_causes'])


def test_known_breakdown_has_no_future_repair_leakage_and_wind_slows_service():
    data, predictions, waiting = tiny_data()
    baseline, _ = projection(data, predictions, waiting)
    data['weather'][0]['wind_mps'] = 15
    windy, _ = projection(data, predictions, waiting)
    assert sum(r['queue_length'] for r in windy) > sum(r['queue_length'] for r in baseline)
    data['availability'] = [dict(crane_id='C00', start=stamp(ORIGIN-timedelta(hours=1)),
        end=stamp(ORIGIN+timedelta(hours=2)), reason='breakdown')]
    one, _ = projection(data, predictions, waiting)
    data['availability'][0]['end'] = stamp(ORIGIN+timedelta(hours=100))
    two, _ = projection(data, predictions, waiting)
    assert one == two
    data['availability'][0]['start'] = stamp(ORIGIN+timedelta(hours=1))
    ignored, _ = projection(data, predictions, waiting)
    data['availability'] = []
    no_future_failure, _ = projection(data, predictions, waiting)
    assert ignored == no_future_failure


def test_more_cranes_reduce_service_with_diminishing_returns_and_full_yard_blocks_handling():
    data, predictions, waiting = tiny_data(calls=1, moves=400)
    baseline, _ = projection(data, predictions, waiting)
    baseline_hours = sum(r['berth_utilisation'] for r in baseline if r['scope'] == 'berth')
    extra = copy.deepcopy(data)
    for i in range(2):
        for j in [2, 3]:
            extra['cranes'].append(dict(id=f'C{i}{j}', berth_id=f'B{i}', equipment='panamax_sts', productivity_moves_per_hour=50))
    faster, _ = projection(extra, predictions, waiting)
    faster_hours = sum(r['berth_utilisation'] for r in faster if r['scope'] == 'berth')
    assert baseline_hours / 2 < faster_hours < baseline_hours
    full = copy.deepcopy(data)
    full['yards'][0]['closing_teu'] = 10000
    blocked, _ = projection(full, predictions, waiting)
    assert all(r['yard_occupancy'] == 1 for r in blocked)
    assert all(r['crane_utilisation'] == 0 for r in blocked)
    assert any(c['code'] == 'HANDLING_BLOCKED_BY_RESOURCES_OR_YARD' for r in blocked for c in r['main_causes'])


def test_confidence_width_and_observation_age_boundaries():
    data, predictions, waiting = tiny_data(calls=0)
    for pred in predictions.values():
        pred['upper'] = .5
    rows, _ = projection(data, predictions, waiting)
    port = [r for r in rows if r['scope'] == 'port']
    assert port[0]['confidence_level'] == port[6]['confidence_level'] == 'MEDIUM'
    assert port[7]['confidence_level'] == 'LOW'
    for pred in predictions.values():
        pred['upper'] += 1e-7
    wide, _ = projection(data, predictions, waiting)
    assert all(r['confidence_level'] == 'LOW' for r in wide)


def test_storm_closure_blocks_new_berthing_and_disabled_alerts_keep_hotspots():
    data, predictions, waiting = tiny_data()
    data['weather'][0]['wind_mps'] = 20
    rows, summaries = projection(data, predictions, waiting, enabled=[])
    assert all(r['berth_utilisation'] == r['crane_utilisation'] == 0 for r in rows)
    assert all(r['rule_breaches'] == [] for r in rows)
    assert all(s['total_hotspot_hours'] > 0 for s in summaries)
    assert any(c['code'] == 'WIND_OR_STORM_REDUCES_PRODUCTIVITY' for r in rows for c in r['main_causes'])


def test_contiguous_hotspots_include_last_hour_and_gaps():
    rows = [dict(timestamp=ORIGIN+timedelta(hours=h), is_hotspot=h in [0, 1, 5, 71]) for h in range(72)]
    windows = hotspot_windows(rows)
    assert [w['duration_hours'] for w in windows] == [2, 1, 1]
    assert windows[-1]['end'] == ORIGIN+timedelta(hours=72)


def test_api_ml_run_persistence_alert_dedup_acknowledgement_and_validation(source, trained, monkeypatch, tmp_path):
    registry, _, _ = trained
    monkeypatch.setenv('MODEL_DIRECTORY', str(registry.directory))
    engine = make_engine(f'sqlite:///{(tmp_path/"warning.db").as_posix()}')
    migrate(engine)
    with session_factory(engine).begin() as session:
        seed_tables(session, *source)
    with TestClient(create_app(replace(get_settings(), auto_migrate=False), engine)) as api:
        payload = dict(as_of=stamp(ORIGIN), port_ids=['P04'])
        first = api.post('/early-warning/run', json=payload)
        assert first.status_code == 201, first.text
        run = first.json()
        assert run['operational_bucket_count'] == (1+6+15)*72
        assert len(run['summaries']) == 22
        assert api.get(f"/early-warning/runs/{run['id']}").json() == run
        buckets = api.get('/early-warning/forecasts', params=dict(run_id=run['id'], scope='port', limit=100)).json()
        assert len(buckets['items']) == 72
        assert all('main_causes' in b and b['model_version'] == run['model_version'] for b in buckets['items'])
        alerts = api.get('/alerts', params=dict(port_id='P04', rule_code='LOW_CONFIDENCE', limit=100)).json()['items']
        assert alerts
        alert = alerts[0]
        ack = api.post(f"/alerts/{alert['id']}/acknowledge", json=dict(actor='Supervisor', expected_revision=alert['revision']))
        assert ack.status_code == 200 and ack.json()['state'] == 'ACKNOWLEDGED'
        assert api.post(f"/alerts/{alert['id']}/acknowledge", json=dict(actor='Other', expected_revision=alert['revision'])).status_code == 409
        second = api.post('/early-warning/run', json=payload)
        assert second.status_code == 201, second.text
        assert second.json()['alert_counts']['opened'] == 0 and second.json()['alert_counts']['refreshed'] > 0
        refreshed = api.get('/alerts', params=dict(port_id='P04', rule_code='LOW_CONFIDENCE', limit=100)).json()['items']
        current = next(a for a in refreshed if a['id'] == alert['id'])
        assert current['state'] == 'ACKNOWLEDGED' and current['acknowledged_by'] == 'Supervisor'
        events = api.get(f"/alerts/{alert['id']}/events").json()['items']
        assert {e['action'] for e in events} == {'OPENED', 'ACKNOWLEDGED', 'REFRESHED'}
        assert api.post('/early-warning/run', json={**payload, 'predictor': 'baseline'}).status_code == 422
        assert api.post('/early-warning/run', json={**payload, 'rules': {'yard_occupancy': 2}}).status_code == 422
        assert api.get('/early-warning/forecasts', params=dict(run_id='missing')).status_code == 404
        assert api.get('/alerts', params=dict(state='invalid')).status_code == 422
        monkeypatch.setenv('ALERT_RULES_FILE', str(tmp_path/'missing.json'))
        assert api.get('/early-warning/rules').status_code == 503
    engine.dispose()


def test_alert_clear_resolution_recurrence_scoped_reconciliation_and_stale_watermark(source, tmp_path):
    engine = make_engine(f'sqlite:///{(tmp_path/"lifecycle.db").as_posix()}')
    migrate(engine)
    with session_factory(engine).begin() as session:
        seed_tables(session, *source)
        repo = AlertRepository(session)
        bid = source[0]['berths'][0]['id']
        tid = source[0]['berths'][0]['terminal_id']
        scope = {('berth', bid)}
        def run(index):
            rid = f'R{index}'
            session.add(m.ForecastRun(id=rid, as_of=ORIGIN, horizon_hours=72, method='test', quality='test', created_at=ORIGIN, input_hash='a'*64))
            session.flush()
            session.add(m.EarlyWarningRun(id=rid, rules={}, projection_method='test', summaries=[], alert_counts={}, assumptions=[]))
            session.flush()
            return rid
        row = dict(scope='berth', scope_id=bid, port_id='P01', terminal_id=tid, berth_id=bid,
            timestamp=ORIGIN, rule_breaches=[dict(code='WAITING_TIME', message='test', evidence=dict(value=9, threshold=8))])
        assert repo.reconcile(run(1), [row], scope)['opened'] == 1
        first = session.scalar(select(m.CongestionAlert))
        assert repo.reconcile(run(2), [], {('port', 'P04')})['resolved'] == 0
        assert first.state == 'OPEN'
        assert repo.reconcile(run(3), [], scope)['resolved'] == 1
        assert first.state == 'RESOLVED' and first.active_key is None
        with pytest.raises(DomainError, match='resolved'):
            repo.acknowledge(first, 'Supervisor', first.revision)
        assert repo.reconcile(run(4), [row], scope)['opened'] == 1
        assert session.scalar(select(func.count()).select_from(m.CongestionAlert)) == 2
        repo.lock_scopes(scope, ORIGIN+timedelta(hours=1))
        with pytest.raises(DomainError) as failure:
            repo.lock_scopes(scope, ORIGIN)
        assert failure.value.code == 'STALE_FORECAST'
    engine.dispose()
