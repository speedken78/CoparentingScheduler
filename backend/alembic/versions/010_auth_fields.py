"""010: add oauth fields to users

Revision ID: 010
Revises: 009
Create Date: 2026-04-22 00:00:10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column(
        'google_sub', sa.Text(), nullable=True
    ))

    op.add_column('users', sa.Column(
        'google_refresh_token_enc', sa.LargeBinary(), nullable=True
    ))

    op.add_column('users', sa.Column(
        'gcal_scope_granted', sa.Boolean(), nullable=False,
        server_default='false'
    ))

    op.add_column('users', sa.Column(
        'last_login_at', sa.TIMESTAMP(timezone=True), nullable=True
    ))

    op.create_index(
        'idx_users_google_sub', 'users', ['google_sub'],
        unique=True,
        postgresql_where=sa.text("google_sub IS NOT NULL")
    )


def downgrade() -> None:
    op.drop_index('idx_users_google_sub', 'users')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'gcal_scope_granted')
    op.drop_column('users', 'google_refresh_token_enc')
    op.drop_column('users', 'google_sub')
