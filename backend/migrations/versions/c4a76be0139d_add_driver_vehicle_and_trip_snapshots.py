"""Record driver vehicles and snapshot their identity when a trip is accepted."""
from alembic import op
import sqlalchemy as sa

revision = 'c4a76be0139d'
down_revision = 'b3c8d1f09e22'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('driver_vehicles',
        sa.Column('driver_id',sa.Integer(),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('registration',sa.String(20),nullable=False),
        sa.Column('model',sa.String(80),nullable=False),
        sa.Column('color',sa.String(40),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False))
    with op.batch_alter_table('rides') as batch:
        batch.add_column(sa.Column('vehicle_registration',sa.String(20)))
        batch.add_column(sa.Column('vehicle_model',sa.String(80)))
        batch.add_column(sa.Column('vehicle_color',sa.String(40)))
    with op.batch_alter_table('admin_audit') as batch:
        batch.add_column(sa.Column('details',sa.Text()))


def downgrade():
    with op.batch_alter_table('admin_audit') as batch:
        batch.drop_column('details')
    with op.batch_alter_table('rides') as batch:
        batch.drop_column('vehicle_color')
        batch.drop_column('vehicle_model')
        batch.drop_column('vehicle_registration')
    op.drop_table('driver_vehicles')
