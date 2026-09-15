"""Engine/session lifecycle and Alembic integration."""
from pathlib import Path
from fastapi import Request

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]


def make_engine(url):
    parsed = make_url(url)
    if parsed.drivername == 'postgresql':
        parsed = parsed.set(drivername='postgresql+psycopg')
    options = {'pool_pre_ping': True}
    if parsed.get_backend_name() == 'postgresql':
        options['connect_args'] = {'connect_timeout': 5}
        options['pool_timeout'] = 5
    if parsed.get_backend_name() == 'sqlite':
        if parsed.database and parsed.database != ':memory:':
            path = Path(parsed.database)
            path = path if path.is_absolute() else ROOT/path
            path.parent.mkdir(parents=True, exist_ok=True)
            parsed = parsed.set(database=str(path.resolve()))
        else:
            options['poolclass'] = StaticPool
        options['connect_args'] = {'check_same_thread': False, 'timeout': 30}
    engine = create_engine(parsed, **options)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def setup(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    return engine


def alembic_config():
    config = Config(str(ROOT/'backend/alembic.ini'))
    config.set_main_option('script_location', str(ROOT/'backend/migrations'))
    return config


def migrate(engine, revision='head'):
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes['connection'] = connection
        command.upgrade(config, revision)


def assert_migration_target(connection):
    tables = set(inspect(connection).get_table_names())
    if tables and 'alembic_version' not in tables:
        raise ValueError('Refusing to migrate an unmanaged database; use a dedicated operational database')


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def get_session(request: Request):
    sessions = getattr(request.state, 'sessions', request.app.state.sessions)
    with sessions() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
