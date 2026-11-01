"""Separate test-only QR payment state."""
from alembic import op
import sqlalchemy as sa
revision = 'f94b12de853e'
down_revision = 'e83a01cf742d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('mock_payments', sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id'), primary_key=True), sa.Column('amount', sa.Numeric(12,2), nullable=False), sa.Column('status', sa.String(16), nullable=False), sa.CheckConstraint("status IN ('PENDING','FAILED','SUCCESS')", name='valid_mock_payment_status'))


def downgrade():
    op.drop_table('mock_payments')
