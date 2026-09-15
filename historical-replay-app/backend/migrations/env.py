from alembic import context

from app.config import get_settings
from app.database import make_engine, assert_migration_target
from app.models import Base
from app.synthetic.storage import UTCInstant

config = context.config


def render_item(kind, obj, autogen_context):
    if kind == 'type' and isinstance(obj, UTCInstant):
        autogen_context.imports.add('from app.synthetic.storage import UTCInstant')
        return 'UTCInstant()'
    return False


def run(connection):
    assert_migration_target(connection)
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_item=render_item, compare_type=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, target_metadata=Base.metadata,
                      literal_binds=True, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get('connection') is not None:
    run(config.attributes['connection'])
else:
    engine = make_engine(get_settings().database_url)
    try:
        with engine.begin() as connection:
            run(connection)
    finally:
        engine.dispose()
