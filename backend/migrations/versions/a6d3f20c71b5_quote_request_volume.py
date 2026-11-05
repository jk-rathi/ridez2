"""Record when fare quotes were requested, for request-volume surge."""
from alembic import op
import sqlalchemy as sa
revision = 'a6d3f20c71b5'
down_revision = 'c51e8a2f90d4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fare_quotes') as batch:
        batch.add_column(sa.Column('created_at', sa.DateTime()))
    op.create_index('ix_fare_quotes_created_at', 'fare_quotes', ['created_at'])


def downgrade():
    op.drop_index('ix_fare_quotes_created_at', 'fare_quotes')
    with op.batch_alter_table('fare_quotes') as batch:
        batch.drop_column('created_at')
