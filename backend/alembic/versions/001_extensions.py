"""001_extensions

Revision ID: 001
Revises:
Create Date: 2026-04-21 00:00:01
"""
from typing import Sequence, Union
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gist"')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS "btree_gist"')
    op.execute('DROP EXTENSION IF EXISTS "pgcrypto"')
