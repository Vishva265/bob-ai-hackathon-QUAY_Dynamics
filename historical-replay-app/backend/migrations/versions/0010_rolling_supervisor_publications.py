"""Rolling supervisor publications and audited state changes.

Revision ID: 0010; Revises: 0009
"""
from alembic import op
import sqlalchemy as sa
from app.synthetic.storage import UTCInstant

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE supervisor_plans SET status = UPPER(status)")
    op.add_column('supervisor_shift_plans', sa.Column('details', sa.JSON(), nullable=True))
    op.add_column('carry_in_operations', sa.Column('remaining_unload_moves', sa.Integer(), nullable=True))
    op.add_column('carry_in_operations', sa.Column('remaining_load_moves', sa.Integer(), nullable=True))
    op.create_table('plan_publications',
        sa.Column('plan_id', sa.String(160), sa.ForeignKey('supervisor_plans.id'), primary_key=True),
        sa.Column('previous_plan_id', sa.String(160), sa.ForeignKey('supervisor_plans.id'), nullable=True),
        sa.Column('document', sa.JSON(), nullable=False),
        sa.Column('generated_at', UTCInstant(), nullable=False),
        sa.Column('reviewed_by', sa.String(120), nullable=True),
        sa.Column('reviewed_at', UTCInstant(), nullable=True))
    op.create_table('plan_state_events',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('plan_id', sa.String(160), sa.ForeignKey('supervisor_plans.id'), nullable=False),
        sa.Column('from_state', sa.String(32), nullable=True),
        sa.Column('to_state', sa.String(32), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('actor', sa.String(120), nullable=False),
        sa.Column('timestamp', UTCInstant(), nullable=False),
        sa.Column('note', sa.String(1000), nullable=False))
    op.create_index('ix_plan_state_events_plan_id', 'plan_state_events', ['plan_id'])
    op.create_table('operational_update_events',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('base_plan_id', sa.String(160), sa.ForeignKey('supervisor_plans.id'), nullable=False),
        sa.Column('state_revision', sa.Integer(), nullable=False),
        sa.Column('actor', sa.String(120), nullable=False),
        sa.Column('timestamp', UTCInstant(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False))
    op.create_index('ix_operational_update_events_base_plan_id', 'operational_update_events', ['base_plan_id'])
    op.create_table('crane_restoration_observations',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('crane_id', sa.String(160), sa.ForeignKey('cranes.id'), nullable=False),
        sa.Column('timestamp', UTCInstant(), nullable=False),
        sa.Column('actor', sa.String(120), nullable=False))
    op.create_index('ix_crane_restoration_observations_crane_id','crane_restoration_observations',['crane_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT id FROM carry_in_operations WHERE remaining_unload_moves IS NOT NULL LIMIT 1')).first():
        raise RuntimeError('Downgrade would lose measured unload/load progress; archive operational data before reversing this migration')
    op.drop_table('crane_restoration_observations')
    op.drop_table('operational_update_events')
    op.drop_table('plan_state_events')
    op.drop_table('plan_publications')
    op.drop_column('carry_in_operations', 'remaining_load_moves')
    op.drop_column('carry_in_operations', 'remaining_unload_moves')
    op.drop_column('supervisor_shift_plans', 'details')
    op.execute("UPDATE supervisor_plans SET status = LOWER(status)")
