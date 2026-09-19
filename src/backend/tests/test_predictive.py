import copy
import json
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import make_engine, migrate, session_factory
from app.main import create_app
from app.predictive import training
from app.predictive.datasets import chronological_splits
from app.predictive.estimators import probabilities
from app.predictive.features import FeatureBuilder, FEATURES, LEVELS, level
from app.predictive.inference import InferenceEngine
from app.predictive.registry import ModelRegistry, ModelArtifactError, _load
from app.services.seed import seed_tables
from app.synthetic.simulator import generate, parse, stamp

EPOCH = '2026-09-13T00:00:00Z'


@pytest.fixture(scope='module')
def source():
    return generate(history_days=3, upcoming_days=3)


def test_features_do_not_use_future_observations_or_unrealised_outcomes(source):
    tables, _ = source
    origin = pd.Timestamp(EPOCH)-timedelta(days=1)
    first = FeatureBuilder(tables).row(origin, origin+timedelta(hours=24), port_id='P04')
    changed = copy.deepcopy(tables)
    for table, fields, delay in [('weather', ['wind_mps', 'visibility_m'], 0), ('tides', ['height_m'], 0),
                                 ('yard_snapshots', ['closing_teu', 'queued_vessels'], 1), ('handling_log', ['handled_moves', 'active_cranes'], 1)]:
        for row in changed[table]:
            if pd.Timestamp(row['timestamp'])+timedelta(hours=delay) > origin:
                for name in fields:
                    row[name] = 999999.
    for row in changed['call_outcomes']:
        row['waiting_hours'] = 99999.
        row['assigned_cranes'] = 999
        row['crane_hours'] = 99999.
        if pd.Timestamp(row['berth_start']) > origin:
            row['berth_id'] = tables['berths'][-1]['id']
            row['berth_start'] = stamp(origin.to_pydatetime()+timedelta(days=100))
        if pd.Timestamp(row['actual_arrival']) > origin:
            row['actual_arrival'] = stamp(origin.to_pydatetime()+timedelta(days=99))
        if pd.Timestamp(row['departure']) > origin:
            row['departure'] = stamp(origin.to_pydatetime()+timedelta(days=101))
    second = FeatureBuilder(changed).row(origin, origin+timedelta(hours=24), port_id='P04')
    assert first == second
    assert set(first) == set(FEATURES)


def test_immediate_yard_reconciliation_is_known_at_its_true_timestamp_only(source):
    tables,_=source;changed=copy.deepcopy(tables);origin=pd.Timestamp(EPOCH)
    terminal=next(t for t in tables['terminals'] if t['port_id']=='P04')
    tid=terminal['id'];before=FeatureBuilder(tables).row(origin,origin,terminal_id=tid)
    observation=dict(id='INSTANT-YARD',terminal_id=tid,timestamp=EPOCH,opening_teu=terminal['yard_capacity_teu']*.8,
        gate_outbound_teu=0,inbound_teu=0,outbound_teu=0,closing_teu=terminal['yard_capacity_teu']*.8,queued_vessels=7)
    changed['yard_snapshots'].append(observation)
    changed['yard_reconciliations']=[dict(snapshot_id='INSTANT-YARD',known_at=EPOCH)]
    after=FeatureBuilder(changed).row(origin,origin,terminal_id=tid)
    assert after['yard_occupancy_pct']==80 and after['queue_length']==7 and after['yard_age_hours']==0
    assert observation['timestamp']==EPOCH
    changed['yard_reconciliations'][0]['known_at']='2026-09-13T01:00:00Z'
    assert FeatureBuilder(changed).row(origin,origin,terminal_id=tid)==before


def test_closed_hour_not_visible_early_and_schedule_changes_are_known(source):
    tables, _ = source
    origin = pd.Timestamp(EPOCH)-timedelta(days=1)+timedelta(minutes=30)
    row1 = FeatureBuilder(tables).row(origin, origin, port_id='P04')
    changed = copy.deepcopy(tables)
    for row in changed['yard_snapshots']:
        if pd.Timestamp(row['timestamp']) == origin.floor('h'):
            row['closing_teu'] = 0
            row['queued_vessels'] = 50
    assert FeatureBuilder(changed).row(origin, origin, port_id='P04') == row1
    call = next(c for c in changed['vessel_calls'] if c['terminal_id'].startswith('P04') and pd.Timestamp(c['scheduled_eta']) > origin)
    call['scheduled_eta'] = stamp(origin.to_pydatetime()+timedelta(hours=1))
    assert FeatureBuilder(changed).row(origin, origin, port_id='P04')['arrivals_next_3h'] != row1['arrivals_next_3h']


def test_fixed_seed_feature_reproducibility_and_no_invented_calendar(source):
    tables, _ = source
    origin = parse(EPOCH)
    one = FeatureBuilder(tables, observation_cutoff=EPOCH).row(origin, origin, terminal_id='P01-T01')
    again, _ = generate(history_days=3, upcoming_days=3)
    two = FeatureBuilder(again, observation_cutoff=EPOCH).row(origin, origin, terminal_id='P01-T01')
    assert one == two
    assert one['holiday_calendar_missing'] == 1 and one['holiday_indicator'] == 0
    assert level(4, .1, 0) == 3 and level(2, .1, 0) == 2 and level(0, .65, 0) == 1 and level(0, .1, 0) == 0


def small_training_rows():
    rng = np.random.default_rng(42)
    waiting, congestion = [], []
    for day in range(60):
        origin = pd.Timestamp('2026-06-01T00:00:00Z')+timedelta(days=day)
        for i in range(25):
            features = dict(zip(FEATURES, rng.uniform(0, 1, len(FEATURES))))
            features.update(lead_hours=i*2, historical_wait_missing=0, waiting_avg_7d=2., **{f'rolling_level_{j}': .25 for j in range(4)})
            known = origin+timedelta(hours=i*2+1)
            waiting.append(dict(features, origin=origin, target_time=known-timedelta(hours=1), label_known_at=known,
                                target=2+features['queue_length']+float(rng.normal(0, .1)), call_id=f'{day}-{i}'))
            congestion.append(dict(features, origin=origin, target_time=known-timedelta(hours=1), label_known_at=known,
                                   target=i%4, scope='port', entity_id='P04'))
    return pd.DataFrame(waiting), pd.DataFrame(congestion)


def test_congestion_threshold_is_selected_without_test_labels():
    y=np.array([0,0,0,2,2,2])
    probabilities=np.array([[.6,.2,.1,.1],[.55,.2,.15,.1],[.5,.2,.2,.1],
                            [.35,.2,.3,.15],[.3,.2,.3,.2],[.25,.15,.35,.25]])
    threshold=training.congestion_threshold(y,probabilities)
    assert .3<=threshold<.5
    assert training.congestion_metrics(y,probabilities,threshold)['f1']>training.congestion_metrics(y,probabilities,.5)['f1']


def test_probability_adapter_normalises_tree_rounding_error():
    class RoundedTree:
        classes_ = np.array([0, 1, 2, 3])

        def predict_proba(self, X):
            return np.tile([.1, .2, .3, .4000000000000001], (len(X), 1))

    result = probabilities(RoundedTree(), pd.DataFrame({'unused': [1, 2]}))
    assert np.all((result >= 0) & (result <= 1))
    assert np.allclose(result.sum(axis=1), 1.)


def test_chronological_split_purges_windows_and_vessel_target_overlap():
    waiting, congestion = small_training_rows()
    for rows in [waiting, congestion]:
        parts = chronological_splits(rows)
        assert parts['train'].label_known_at.max() < parts['validation'].origin.min()
        assert parts['validation'].label_known_at.max() < parts['test'].origin.min()
    parts = chronological_splits(waiting)
    assert set(parts['train'].call_id).isdisjoint(parts['test'].call_id)
    assert sum(len(p) for p in parts.values()) < len(waiting)


@pytest.fixture
def trained(tmp_path, monkeypatch):
    rows = small_training_rows()
    monkeypatch.setattr(training, 'build_training_rows', lambda *a: rows)
    metadata, path = training.train_pipeline({}, dict(epoch=EPOCH, scenario='unit_fixture', seed=42), tmp_path/'models', progress=None)
    return ModelRegistry(tmp_path/'models'), metadata, path


def test_persistence_inference_ordered_bands_local_factors_and_immutable_version(trained, monkeypatch):
    registry, metadata, path = trained
    engine = InferenceEngine(registry)
    waiting, congestion = small_training_rows()
    for task, rows in [('waiting', waiting), ('congestion', congestion)]:
        result = engine.predict(task, rows[FEATURES].iloc[:5].to_dict('records'))
        assert all(r['lower'] <= r['prediction'] <= r['upper'] for r in result)
        assert all(r['model_version'] == metadata['model_version'] and r['prediction_timestamp'].endswith('+00:00') for r in result)
        if task == 'congestion':
            assert all(r['level'] in LEVELS and abs(sum(r['level_probabilities'].values())-1) < 1e-6 for r in result)
    assert set(metadata['evaluation']['waiting']['metrics']) == {'rolling_average', 'linear', 'hist_gradient_boosting'}
    assert metadata['evaluation']['congestion']['metrics']['logistic']['test']['confusion_matrix']
    assert metadata['evaluation']['waiting']['uncertainty']['test_coverage'] >= 0
    with pytest.raises(ValueError, match='immutable'):
        training.train_pipeline({}, dict(epoch=EPOCH, scenario='unit_fixture', seed=42), registry.directory, progress=None)
    _load.cache_clear()
    with (path/'models.joblib').open('ab') as handle:
        handle.write(b'tampered')
    with pytest.raises(ModelArtifactError, match='checksum'):
        registry.load()


def test_cached_model_detects_replaced_artifact_without_manual_cache_clear(trained):
    registry,_,path=trained
    registry.load()
    with (path/'models.joblib').open('ab') as handle:handle.write(b'corrupt cache input')
    with pytest.raises(ModelArtifactError,match='checksum'):registry.load()


@pytest.mark.parametrize('change',[{'files':[]},{'files':{}},{'units':{}},{'features':['invented']}])
def test_model_manifest_schema_fails_closed_before_inference(trained,change):
    import hashlib
    registry,metadata,path=trained
    registry.load()
    metadata.update(change)
    target=path/'metadata.json';target.write_text(json.dumps(metadata))
    pointer={'model_version':metadata['model_version'],'metadata_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    (registry.directory/'active.json').write_text(json.dumps(pointer))
    with pytest.raises(ModelArtifactError):registry.load()


def test_ml_api_predictive_results_and_explicit_missing_model(trained, source, monkeypatch, tmp_path):
    registry, metadata, _ = trained
    monkeypatch.setenv('MODEL_DIRECTORY', str(registry.directory))
    engine = make_engine(f'sqlite:///{(tmp_path/"operations.db").as_posix()}')
    migrate(engine)
    with session_factory(engine).begin() as session:
        seed_tables(session, *source)
    with TestClient(create_app(replace(get_settings(), auto_migrate=False), engine)) as api:
        result = api.post('/forecasts/run', json={'as_of': EPOCH, 'port_ids': ['P04'], 'predictor': 'ml'})
        assert result.status_code == 201, result.text
        run = result.json()
        assert run['model_version'] == metadata['model_version'] and run['predictive_bucket_count'] == 7*72
        assert api.get('/predictions/models/current').json()['model_version'] == metadata['model_version']
        assert run['waiting_prediction_count'] > 0
        congestion = api.get('/predictions/congestion', params={'run_id': run['id'], 'scope': 'port', 'limit': 100}).json()
        assert len(congestion['items']) == 72
        waits = api.get('/predictions/waiting-time', params={'run_id': run['id']}).json()
        assert waits['items'] and all(r['prediction'] >= 0 and r['lower'] <= r['upper'] for r in waits['items'])
        assert api.get('/predictions/congestion', params={'run_id':'unknown'}).status_code == 404
        assert api.get('/predictions/congestion', params={'scope':'made_up'}).status_code == 422
        monkeypatch.setenv('MODEL_DIRECTORY', str(tmp_path/'missing'))
        missing = api.post('/forecasts/run', json={'as_of': EPOCH, 'port_ids': ['P04'], 'predictor': 'ml'})
        assert missing.status_code == 503 and missing.json()['error']['code'] == 'MODEL_UNAVAILABLE'
        assert api.get('/predictions/models/current').status_code == 503
        baseline = api.post('/forecasts/run', json={'as_of': EPOCH, 'port_ids': ['P04'], 'predictor': 'baseline'})
        assert baseline.status_code == 201 and baseline.json()['model_version'] is None


def test_unknown_repair_end_cannot_improve_future_capacity(source):
    tables, _ = source
    origin = pd.Timestamp(EPOCH)-timedelta(days=1)
    changed = copy.deepcopy(tables)
    changed['crane_availability'].append(dict(id='test', crane_id=tables['cranes'][0]['id'], start=(origin-timedelta(hours=1)).isoformat(),
        end=(origin+timedelta(hours=2)).isoformat(), reason='breakdown', disruption_id=None))
    one = FeatureBuilder(changed).row(origin, origin+timedelta(hours=12), terminal_id='P01-T01')
    changed['crane_availability'][-1]['end'] = (origin+timedelta(hours=100)).isoformat()
    two = FeatureBuilder(changed).row(origin, origin+timedelta(hours=12), terminal_id='P01-T01')
    assert one == two


def test_calibration_quantile_and_single_class_auc_are_explicit():
    assert training.quantile_radius([1, 2, 3, 4], .9) == 4
    metrics = training.congestion_metrics([0, 0], np.array([[1., 0, 0, 0], [1., 0, 0, 0]]))
    assert metrics['roc_auc'] is None and metrics['f1'] == 0


def test_standalone_alembic_cli_commits_revision_in_new_database(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy import text
    url = f'sqlite:///{(tmp_path/"standalone.db").as_posix()}'
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', 'backend/alembic.ini', 'upgrade', 'head'],
                            cwd=root, env={**os.environ, 'DATABASE_URL': url}, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    engine = make_engine(url)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0012'
    engine.dispose()


def test_model_inference_refuses_lookahead_and_nonfinite_features(trained, source):
    registry, metadata, _ = trained
    engine = InferenceEngine(registry)
    tables, _ = source
    before = metadata['evaluation']['waiting']['splits']['train']['origin_start']
    with pytest.raises(ValueError, match='training/calibration'):
        engine.forecast(tables, before, ['P04'])
    rows = small_training_rows()[0][FEATURES].iloc[:1].to_dict('records')
    rows[0]['wind_mps'] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        engine.predict('waiting', rows)


def test_observed_event_seed_closes_training_serving_gap_and_excludes_future(source, tmp_path):
    from sqlalchemy import select
    from app import models as m
    from app.services.operations import record
    from app.services.observations import seed_observations
    tables, manifest = source
    engine = make_engine(f'sqlite:///{(tmp_path/"parity.db").as_posix()}')
    migrate(engine)
    with session_factory(engine).begin() as session:
        seed_tables(session, tables, manifest)
        events = [record(r) for r in session.scalars(select(m.VesselCallObservation))]
        assert events and all(pd.Timestamp(r['timestamp']) <= pd.Timestamp(EPOCH) for r in events)
        assert seed_observations(session, tables, EPOCH)['inserted'] == 0
        database = {name: [dict(row) for row in session.execute(select(table)).mappings()] for name, table in m.source_tables.items()}
        database['vessel_call_observations'] = events
        database['carry_in_operations'] = [record(r) for r in session.scalars(select(m.CarryInOperation))]
    source_builder = FeatureBuilder(tables, observation_cutoff=EPOCH)
    db_builder = FeatureBuilder(database)
    for port in ['P01', 'P04']:
        one = source_builder.row(EPOCH, pd.Timestamp(EPOCH)+timedelta(hours=12), port_id=port)
        two = db_builder.row(EPOCH, pd.Timestamp(EPOCH)+timedelta(hours=12), port_id=port)
        assert one == pytest.approx(two)
    engine.dispose()


def test_existing_version_is_rejected_before_expensive_feature_generation(trained, monkeypatch):
    registry, _, _ = trained
    monkeypatch.setattr(training, 'build_training_rows', lambda *args: pytest.fail('An immutable duplicate must fail before rebuilding features'))
    with pytest.raises(ValueError, match='immutable'):
        training.train_pipeline({}, dict(epoch=EPOCH, scenario='unit_fixture', seed=42), registry.directory, progress=None)


def test_quiet_port_without_any_vessel_calls_has_forecast_and_empty_waiting(trained, source):
    registry, _, _ = trained
    tables = copy.deepcopy(source[0])
    for name in ['vessel_calls', 'vessels', 'call_outcomes', 'handling_log', 'crane_assignments']:
        tables[name] = []
    for yard in tables['yard_snapshots']:
        yard['queued_vessels'] = 0
    result = InferenceEngine(registry).forecast(tables, EPOCH, ['P04'], observation_cutoff=EPOCH, explain=False)
    assert len(result['congestion']) == 7*72 and result['waiting'] == []
