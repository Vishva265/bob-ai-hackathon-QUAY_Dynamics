"""Durable job leases and operational lookup indexes."""
from alembic import op
import sqlalchemy as sa
from app.synthetic.storage import UTCInstant

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

INDEXES = [
    ('supervisor_plans', ['status', 'approved_at']),
    ('optimisation_runs', ['created_at']),
    ('operational_forecasts', ['run_id', 'port_id', 'timestamp']),
    ('crane_availability', ['crane_id', 'start', 'end']),
    ('crane_restoration_observations', ['crane_id', 'timestamp']),
    ('berth_closure_windows', ['berth_id', 'start', 'end']),
    ('yard_capacity_observations', ['terminal_id', 'timestamp']),
    ('live_demo_events', ['session_id', 'sequence']),
]

def upgrade():
    op.create_table('optimisation_job_leases', sa.Column('id', sa.String(80), primary_key=True),
        sa.Column('owner', sa.String(64), nullable=False), sa.Column('expires_at', UTCInstant(), nullable=False))
    op.create_index('ix_optimisation_job_leases_expires_at', 'optimisation_job_leases', ['expires_at'])
    for table, columns in INDEXES:
        name = 'ix_'+table+'_readiness'
        if name not in {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, columns)

def downgrade():
    for table, _ in reversed(INDEXES):
        op.drop_index('ix_'+table+'_readiness', table_name=table)
    op.drop_index('ix_optimisation_job_leases_expires_at', table_name='optimisation_job_leases')
    op.drop_table('optimisation_job_leases')
