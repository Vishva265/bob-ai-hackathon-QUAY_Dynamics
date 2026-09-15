import copy
import hashlib
import os
import sqlite3

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.exc import IntegrityError

from app.synthetic.files import csv_bytes, export_dataset, read_dataset
from app.synthetic.simulator import effective_rate, generate, weather_factor
from app.synthetic.storage import connect, database_schema, seed_database
from app.synthetic.validation import DataValidationError, validate


@pytest.fixture(scope='module')
def demo():
    return generate(seed=42, history_days=2, upcoming_days=1)


def hashes(tables):
    return {name: hashlib.sha256(csv_bytes(name, rows)).hexdigest() for name, rows in tables.items()}


def test_fixed_seed_reproduces_every_export_byte(demo):
    tables, manifest = demo
    repeated, repeated_manifest = generate(seed=42, history_days=2, upcoming_days=1)
    assert hashes(tables) == hashes(repeated)
    assert manifest == repeated_manifest
    changed, _ = generate(seed=43, history_days=2, upcoming_days=1)
    assert hashes(changed) != hashes(tables)


def test_all_business_rules_and_normalized_export_round_trip(demo, tmp_path):
    tables, manifest = demo
    assert validate(tables, manifest)['valid']
    exported = export_dataset(tmp_path/'normal', tables, manifest)
    restored, read_manifest, report = read_dataset(tmp_path/'normal')
    assert restored == tables
    assert read_manifest == exported
    assert report['valid']
    assert len(tables['ports']) == 4
    assert {sum(t['port_id'] == p['id'] for t in tables['terminals']) for p in tables['ports']} == {3, 4, 5, 6}
    upcoming = (tmp_path/'normal'/'upcoming'/'vessel_calls.csv').read_text()
    assert 'actual_arrival' not in upcoming
    assert 'upcoming' in upcoming
    assert 'simulated_future_truth' not in (tmp_path/'normal'/'historical'/'call_outcomes.csv').read_text()


@pytest.mark.parametrize(('table', 'field', 'value', 'message'), [
    ('vessel_calls', 'unload_moves', -1, 'negative quantity'),
    ('vessel_calls', 'terminal_id', 'MISSING', 'broken reference'),
    ('vessel_calls', 'priority', 8, 'priority'),
    ('vessel_calls', 'scheduled_eta', '2026-09-12T00:00:00', 'UTC timestamp'),
    ('call_outcomes', 'departure', '2020-01-01T00:00:00Z', 'timestamps'),
    ('yard_snapshots', 'closing_teu', 999999, 'capacity violation'),
    ('handling_log', 'handled_moves', 999999, 'throughput mismatch'),
    ('call_outcomes', 'period', 'historical', 'future outcome leakage'),
])
def test_validator_rejects_corruption(demo, table, field, value, message):
    tables, manifest = demo
    damaged = copy.deepcopy(tables)
    index = next(i for i, r in enumerate(damaged[table]) if r['period'] == 'simulated_future_truth') if field == 'period' else 0
    damaged[table][index][field] = value
    with pytest.raises(DataValidationError, match=message):
        validate(damaged, manifest)


def test_duplicate_ids_and_export_tampering_are_rejected(demo, tmp_path):
    tables, manifest = demo
    damaged = copy.deepcopy(tables)
    damaged['ports'].append(damaged['ports'][0])
    with pytest.raises(DataValidationError, match='duplicate IDs'):
        validate(damaged, manifest)
    export_dataset(tmp_path/'demo', tables, manifest)
    with (tmp_path/'demo'/'ports.csv').open('a') as handle:
        handle.write('tampered\n')
    with pytest.raises(DataValidationError, match='checksum mismatch'):
        read_dataset(tmp_path/'demo')


def test_extended_berth_occupation_cannot_overlap_another_visit(demo):
    tables, manifest = demo
    damaged = copy.deepcopy(tables)
    groups = {}
    for o in damaged['call_outcomes']:
        groups.setdefault(o['berth_id'], []).append(o)
    group = next(rows for rows in groups.values() if len(rows) >= 2)
    group.sort(key=lambda o: o['berth_start'])
    group[0]['departure'] = group[1]['departure']
    group[0]['period'] = group[1]['period']
    with pytest.raises(DataValidationError, match='overlapping assignments'):
        validate(damaged, manifest)


def test_volume_cranes_weather_and_occupancy_have_causal_effects():
    one = effective_rate([30], 5, 0, 3000, 10000)
    two = effective_rate([30, 30], 5, 0, 3000, 10000)
    three = effective_rate([30, 30, 30], 5, 0, 3000, 10000)
    assert one < two < three
    assert two-one > three-two
    assert 2000/two > 1000/two
    assert effective_rate([30, 30], 16, 0, 3000, 10000) < two
    assert effective_rate([30, 30], 5, 0, 9000, 10000) < two
    assert weather_factor(20, 0) == 0
    assert effective_rate([], 5, 0, 3000, 10000) == 0


def test_named_scenarios_create_queues_and_weather_equipment_delays():
    runs = {scenario: generate(history_days=2, upcoming_days=3, scenario=scenario)
            for scenario in ['normal_operations', 'arrival_surge', 'storm_crane_breakdown']}
    waits = {}
    histories = {}
    for scenario, (tables, manifest) in runs.items():
        assert validate(tables, manifest)['valid']
        target = {r['id'] for r in tables['vessel_calls'] if r['terminal_id'] == 'P01-T01' and r['period'] == 'upcoming'}
        waits[scenario] = sum(o['waiting_hours'] for o in tables['call_outcomes'] if o['call_id'] in target)/len(target)
        histories[scenario] = hashes({'vessel_calls': [r for r in tables['vessel_calls'] if r['period'] == 'historical']})
    assert len({str(h) for h in histories.values()}) == 1
    assert waits['arrival_surge'] > waits['normal_operations']
    assert waits['storm_crane_breakdown'] > waits['normal_operations']
    surge, _ = runs['arrival_surge']
    assert max(r['queued_vessels'] for r in surge['yard_snapshots'] if r['terminal_id'] == 'P01-T01') >= 10
    storm, _ = runs['storm_crane_breakdown']
    assert any(r['weather_factor'] == 0 and r['handled_moves'] == 0 for r in storm['handling_log'])
    assert any(r['reason'] == 'breakdown' for r in storm['crane_availability'])


def test_seed_database_integrity_round_trip_and_safe_replacement(demo, tmp_path):
    tables, manifest = demo
    url = f'sqlite:///{(tmp_path/"demo.db").as_posix()}'
    report = seed_database(url, tables, manifest)
    assert report['seeded_rows'] == sum(len(rows) for rows in tables.values())
    metadata, db_tables, _ = database_schema()
    engine = connect(url)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
            assert connection.exec_driver_sql('PRAGMA foreign_key_check').all() == []
            rows = connection.execute(select(db_tables['vessel_calls'])).mappings().all()
            assert sorted((dict(r) for r in rows), key=lambda r: r['id']) == tables['vessel_calls']
    finally:
        engine.dispose()
    with pytest.raises(ValueError, match='already seeded'):
        seed_database(url, tables, manifest)
    assert seed_database(url, tables, manifest, replace_demo=True)['seeded_rows'] == report['seeded_rows']
    with sqlite3.connect(tmp_path/'demo.db') as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        connection.execute('CREATE TABLE unrelated (id INTEGER)')
    with pytest.raises(ValueError, match='non-demo database'):
        seed_database(url, tables, manifest, replace_demo=True)


def test_postgres_schema_uses_native_timezone_and_foreign_keys():
    metadata, _, _ = database_schema()
    ddl = '\n'.join(str(CreateTable(t).compile(dialect=postgresql.dialect())) for t in metadata.sorted_tables)
    assert 'TIMESTAMP WITH TIME ZONE' in ddl
    assert 'FOREIGN KEY' in ddl


@pytest.mark.skipif(not os.getenv('PORT_SIM_TEST_DATABASE_URL'), reason='Dedicated PostgreSQL test URL not configured')
def test_postgresql_seed_round_trip_and_constraints(demo):
    tables, manifest = demo
    url = os.environ['PORT_SIM_TEST_DATABASE_URL']
    assert url.startswith('postgresql')
    seed_database(url, tables, manifest, replace_demo=True)
    _, db_tables, _ = database_schema()
    engine = connect(url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(select(db_tables['call_outcomes'])).mappings().all()
            assert sorted((dict(r) for r in rows), key=lambda r: r['id']) == tables['call_outcomes']
        bad = dict(tables['cranes'][0], id='BAD', berth_id='MISSING')
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(db_tables['cranes'].insert(), bad)
        with engine.connect() as connection:
            assert connection.execute(select(db_tables['cranes']).where(db_tables['cranes'].c.id == 'BAD')).first() is None
    finally:
        engine.dispose()


@pytest.mark.parametrize('scenario', ['arrival_surge', 'storm_crane_breakdown'])
def test_stress_scenarios_are_also_byte_reproducible(scenario):
    first, manifest = generate(history_days=2, upcoming_days=1, scenario=scenario)
    second, repeated_manifest = generate(history_days=2, upcoming_days=1, scenario=scenario)
    assert hashes(first) == hashes(second)
    assert manifest == repeated_manifest


def test_empty_or_unowned_directory_is_not_overwritten(demo, tmp_path):
    tables, manifest = demo
    (tmp_path/'important.txt').write_text('existing work')
    with pytest.raises(ValueError, match='without a demo manifest'):
        export_dataset(tmp_path, tables, manifest)
    assert (tmp_path/'important.txt').read_text() == 'existing work'
