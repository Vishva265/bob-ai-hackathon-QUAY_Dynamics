"""Immutable end-to-end recommendation comparisons.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from app.synthetic.storage import UTCInstant

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recommendation_runs',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('source_run_id', sa.String(160), sa.ForeignKey('optimisation_runs.id'), nullable=False),
        sa.Column('as_of', UTCInstant(), nullable=False),
        sa.Column('created_at', UTCInstant(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('model_version', sa.String(64), nullable=False),
        sa.Column('input_snapshot', sa.JSON(), nullable=False),
        sa.Column('policy', sa.JSON(), nullable=False),
        sa.Column('summary', sa.JSON(), nullable=False),
        sa.Column('source_revision', sa.Integer(), nullable=False))
    op.create_index('ix_recommendation_runs_source_run_id', 'recommendation_runs', ['source_run_id'])
    op.create_table('recommendation_decisions',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('run_id', sa.String(160), sa.ForeignKey('recommendation_runs.id'), nullable=False),
        sa.Column('call_id', sa.String(160), sa.ForeignKey('vessel_calls.id'), nullable=False),
        sa.Column('port_id', sa.String(160), sa.ForeignKey('ports.id'), nullable=False),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('expires_at', UTCInstant(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.UniqueConstraint('run_id', 'call_id'),
        sa.CheckConstraint("action IN ('KEEP_CURRENT_PLAN', 'SLOW_STEAM_OR_DELAY_ARRIVAL', 'EARLIER_ARRIVAL', 'ALTERNATE_TERMINAL', 'ALTERNATE_PORT')"))
    op.create_index('ix_recommendation_decisions_run_id', 'recommendation_decisions', ['run_id'])
    op.create_index('ix_recommendation_decisions_call_id', 'recommendation_decisions', ['call_id'])


def downgrade():
    op.drop_table('recommendation_decisions')
    op.drop_table('recommendation_runs')
