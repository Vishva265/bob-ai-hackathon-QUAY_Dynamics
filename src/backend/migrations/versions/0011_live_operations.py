"""Isolated live demos and observed resource restrictions."""
from alembic import op
from app import models as m

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    for model in (m.LiveDemoSession, m.LiveDemoEvent, m.BerthClosureWindow, m.YardCapacityObservation, m.LiveDemoReceipt, m.KnownStormAdvisory, m.YardReconciliation):
        model.__table__.create(op.get_bind())


def downgrade():
    for model in (m.YardReconciliation, m.KnownStormAdvisory, m.LiveDemoReceipt, m.YardCapacityObservation, m.BerthClosureWindow, m.LiveDemoEvent, m.LiveDemoSession):
        model.__table__.drop(op.get_bind())
