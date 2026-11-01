"""Record cash/online payment per completed ride; earnings count only after confirmation."""
from alembic import op
import sqlalchemy as sa
revision = '7ba01cddd40c'
down_revision = 'f94b12de853e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ride_payments',
        sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id'), primary_key=True),
        sa.Column('method', sa.String(16)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('amount', sa.Numeric(10, 2), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('confirmed_at', sa.DateTime()),
        sa.Column('confirmed_by', sa.Integer(), sa.ForeignKey('users.id')),
        sa.CheckConstraint("status IN ('PENDING','CONFIRMED')", name='valid_ride_payment_status'),
        sa.CheckConstraint("method IS NULL OR method IN ('CASH','ONLINE','UNRECORDED')", name='valid_ride_payment_method'),
        sa.CheckConstraint("status = 'PENDING' OR (method IS NOT NULL AND confirmed_at IS NOT NULL)", name='confirmed_ride_payment_complete'))
    # Trips completed before payment tracking keep their earnings: treat them as already settled.
    op.execute("""
        INSERT INTO ride_payments (ride_id, method, status, amount, updated_at, confirmed_at)
        SELECT r.id,
               CASE WHEN m.status = 'SUCCESS' THEN 'ONLINE' ELSE 'UNRECORDED' END,
               'CONFIRMED', q.total, r.completed_at, r.completed_at
        FROM rides r
        JOIN fare_quotes q ON q.id = r.quote_id
        LEFT JOIN mock_payments m ON m.ride_id = r.id
        WHERE r.status = 'COMPLETED' AND r.completed_at IS NOT NULL
    """)


def downgrade():
    op.drop_table('ride_payments')
