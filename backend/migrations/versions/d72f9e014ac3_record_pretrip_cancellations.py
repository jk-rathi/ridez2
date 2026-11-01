"""Record attributed pre-trip cancellation reasons and timestamps."""
from alembic import op
import sqlalchemy as sa

revision = 'd72f9e014ac3'
down_revision = 'c4a76be0139d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('rides') as batch:
        batch.add_column(sa.Column('cancelled_at',sa.DateTime()))
        batch.add_column(sa.Column('cancelled_by',sa.Integer()))
        batch.add_column(sa.Column('cancellation_reason',sa.String(300)))
        batch.create_foreign_key('fk_rides_cancelled_by_users','users',['cancelled_by'],['id'])


def downgrade():
    with op.batch_alter_table('rides') as batch:
        batch.drop_constraint('fk_rides_cancelled_by_users',type_='foreignkey')
        batch.drop_column('cancellation_reason')
        batch.drop_column('cancelled_by')
        batch.drop_column('cancelled_at')
