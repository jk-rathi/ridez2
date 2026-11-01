"""Remember whether a busy driver wants to remain available after completion."""
from alembic import op
import sqlalchemy as sa

revision = 'e83a01cf742d'
down_revision = 'd72f9e014ac3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('driver_presence') as batch:
        batch.add_column(sa.Column('resume_available',sa.Boolean(),nullable=False,server_default=sa.true()))


def downgrade():
    with op.batch_alter_table('driver_presence') as batch:
        batch.drop_column('resume_available')
