"""Add driver suspension, version guards and immutable review snapshots."""
from alembic import op
import sqlalchemy as sa

revision = 'b3c8d1f09e22'
down_revision = '9f22dbe09a11'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users') as batch:
        batch.add_column(sa.Column('status_revision',sa.Integer(),nullable=False,server_default='0'))
        batch.drop_constraint('valid_user_status',type_='check')
        batch.create_check_constraint('valid_user_status',"status IN ('active','pending','disabled','suspended') AND (status != 'suspended' OR role = 'driver')")
    with op.batch_alter_table('admin_audit') as batch:
        batch.add_column(sa.Column('before_status',sa.String(16)))
        batch.add_column(sa.Column('after_status',sa.String(16)))
        batch.add_column(sa.Column('status_revision',sa.Integer()))


def downgrade():
    # A downgrade must not silently reinstate suspended drivers.
    count=op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE status = 'suspended'")).scalar()
    if count:
        raise RuntimeError('Review and reinstate suspended drivers before downgrading')
    with op.batch_alter_table('admin_audit') as batch:
        batch.drop_column('status_revision')
        batch.drop_column('after_status')
        batch.drop_column('before_status')
    with op.batch_alter_table('users') as batch:
        batch.drop_constraint('valid_user_status',type_='check')
        batch.create_check_constraint('valid_user_status',"status IN ('active','pending','disabled')")
        batch.drop_column('status_revision')
