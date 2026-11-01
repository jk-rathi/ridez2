"""Add revocable sessions and single-use refresh credential hashes."""
from alembic import op
import sqlalchemy as sa

revision = '9f22dbe09a11'
down_revision = '5854899d25f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_sessions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime()))
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_table('refresh_tokens',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('session_id', sa.String(36), sa.ForeignKey('auth_sessions.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime()))
    op.create_index('ix_refresh_tokens_session_id', 'refresh_tokens', ['session_id'])


def downgrade():
    op.drop_table('refresh_tokens')
    op.drop_table('auth_sessions')
