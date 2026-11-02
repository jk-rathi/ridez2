"""Two-way star ratings for completed rides."""
from alembic import op
import sqlalchemy as sa
revision = 'c51e8a2f90d4'
down_revision = '7ba01cddd40c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ride_ratings',
        sa.Column('ride_id', sa.String(36), sa.ForeignKey('rides.id'), primary_key=True),
        sa.Column('rater_role', sa.String(8), primary_key=True),
        sa.Column('rater_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ratee_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('stars', sa.Integer(), nullable=False),
        sa.Column('tags', sa.String(200)),
        sa.Column('comment', sa.String(300)),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint("rater_role IN ('rider','driver')", name='valid_rating_role'),
        sa.CheckConstraint('stars BETWEEN 1 AND 5', name='valid_rating_stars'))
    op.create_index('ix_ride_ratings_ratee_id', 'ride_ratings', ['ratee_id'])


def downgrade():
    op.drop_index('ix_ride_ratings_ratee_id', 'ride_ratings')
    op.drop_table('ride_ratings')
