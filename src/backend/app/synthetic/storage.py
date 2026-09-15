"""Portable, transactional demo database seeding; never clears application tables."""
from datetime import timezone

from sqlalchemy import (CheckConstraint, Column, DateTime, Float, ForeignKey,
                        Integer, MetaData, String, Table, UniqueConstraint,
                        create_engine, event, inspect, select)
from sqlalchemy.types import TypeDecorator

from .schema import ENUMS, SCHEMA
from .simulator import parse, stamp
from .validation import validate


class UTCInstant(TypeDecorator):
    """Native timestamptz on PostgreSQL, explicit UTC text on SQLite."""
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(DateTime(timezone=True) if dialect.name == 'postgresql' else String(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        dt = parse(value) if isinstance(value, str) else value
        if dt.tzinfo is None:
            raise ValueError('Naive database timestamp')
        return dt.astimezone(timezone.utc) if dialect.name == 'postgresql' else stamp(dt)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return stamp(value) if dialect.name == 'postgresql' else value


def database_schema():
    metadata = MetaData()
    tables = {}
    natural_keys = {
        'berth_cargo_compatibility': ('berth_id', 'cargo_type'),
        'vessel_calls': ('vessel_id',),
        'call_outcomes': ('call_id',),
        'weather': ('port_id', 'timestamp'),
        'tides': ('port_id', 'timestamp'),
        'yard_snapshots': ('terminal_id', 'timestamp'),
        'handling_log': ('call_id', 'timestamp'),
        'crane_assignments': ('call_id', 'crane_id'),
    }
    for name, fields in SCHEMA.items():
        columns, constraints = [], []
        for key, field in fields.items():
            kind = {'str': String(160), 'int': Integer(), 'float': Float(), 'time': UTCInstant()}[field.kind]
            args = [ForeignKey(f'{field.reference}.id', ondelete='RESTRICT')] if field.reference else []
            columns.append(Column(key, kind, *args, primary_key=key == 'id', nullable=field.nullable))
            if field.kind in ('float', 'int') and (name, key) not in {('ports', 'latitude'), ('ports', 'longitude'), ('tides', 'height_m')}:
                constraints.append(CheckConstraint(f'{key} >= 0'))
            if (name, key) in ENUMS:
                choices = ','.join("'" + v + "'" for v in sorted(ENUMS[(name, key)]))
                constraints.append(CheckConstraint(f'{key} IN ({choices})'))
        if name in natural_keys:
            constraints.append(UniqueConstraint(*natural_keys[name]))
        if 'start' in fields and 'end' in fields:
            constraints.append(CheckConstraint('"end" > "start"'))
        if name == 'terminals':
            constraints.append(CheckConstraint('initial_yard_teu <= yard_capacity_teu AND yard_capacity_teu > 0'))
        if name == 'vessel_calls':
            constraints.append(CheckConstraint('priority BETWEEN 1 AND 5 AND teu_per_move BETWEEN 1 AND 2'))
        if name == 'call_outcomes':
            constraints.append(CheckConstraint('berth_start >= actual_arrival AND service_completion > berth_start AND departure >= service_completion'))
        tables[name] = Table(name, metadata, *columns, *constraints)
    marker = Table('demo_dataset', metadata, Column('id', Integer, primary_key=True),
                   Column('generator_version', String(32), nullable=False),
                   Column('scenario', String(64), nullable=False),
                   Column('seed', Integer, nullable=False), Column('epoch', UTCInstant(), nullable=False))
    return metadata, tables, marker


def connect(url):
    if url.startswith('postgresql://'):
        url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
    engine = create_engine(url)
    if engine.dialect.name not in {'sqlite', 'postgresql'}:
        engine.dispose()
        raise ValueError('Only SQLite and PostgreSQL are supported')
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def enable_fk(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine


def seed_database(url, tables, manifest, replace_demo=False):
    """Validate before opening DB; allow replacement only in an owned demo database."""
    report = validate(tables, manifest)
    metadata, sql_tables, marker = database_schema()
    engine = connect(url)
    try:
        existing = set(inspect(engine).get_table_names())
        expected = set(metadata.tables)
        if existing and (not existing <= expected or 'demo_dataset' not in existing):
            raise ValueError('Refusing to seed a non-demo database; use a dedicated demo database')
        with engine.begin() as connection:
            if existing:
                old = connection.execute(select(marker)).mappings().first()
                if old is None or old['id'] != 1:
                    raise ValueError('Database has no valid demo ownership marker')
                if not replace_demo:
                    raise ValueError('Demo database already seeded; pass --replace-demo to regenerate it')
                if old['scenario'] != manifest['scenario']:
                    raise ValueError('Refusing to replace a different scenario database')
            metadata.create_all(connection)
            if existing:
                for table in reversed(metadata.sorted_tables):
                    connection.execute(table.delete())
            for table in metadata.sorted_tables:
                if table is marker:
                    continue
                rows = tables[table.name]
                for offset in range(0, len(rows), 1000):
                    connection.execute(table.insert(), rows[offset:offset+1000])
            connection.execute(marker.insert(), dict(id=1, generator_version=manifest['generator_version'],
                scenario=manifest['scenario'], seed=manifest['seed'], epoch=manifest['epoch']))
        return dict(validated=report, seeded_rows=report['rows'], tables=len(sql_tables), dialect=engine.dialect.name)
    finally:
        engine.dispose()
