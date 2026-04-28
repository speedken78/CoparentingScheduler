"""002_users_and_cases

Revision ID: 002
Revises: 001
Create Date: 2026-04-21 00:00:02
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, BYTEA, JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email           TEXT UNIQUE NOT NULL,
            phone           TEXT,
            display_name    TEXT NOT NULL,
            role            TEXT NOT NULL CHECK (role IN ('parent','lawyer','social_worker','admin')),
            line_user_id    TEXT UNIQUE,
            google_oauth_token_enc BYTEA,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at      TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL")

    op.execute("""
        CREATE TABLE family_cases (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_name       TEXT NOT NULL,
            court_case_no   TEXT,
            custody_type    TEXT NOT NULL CHECK (custody_type IN ('sole','joint','split')),
            custody_ratio   JSONB,
            timezone        TEXT NOT NULL DEFAULT 'Asia/Taipei',
            created_by      UUID NOT NULL REFERENCES users(id),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at      TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE case_memberships (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id         UUID NOT NULL REFERENCES family_cases(id),
            user_id         UUID NOT NULL REFERENCES users(id),
            relation        TEXT NOT NULL CHECK (relation IN ('parent_a','parent_b','lawyer','observer')),
            permissions     JSONB NOT NULL DEFAULT jsonb_build_object('read', true, 'write', true),
            invited_by      UUID REFERENCES users(id),
            joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at      TIMESTAMPTZ,
            UNIQUE (case_id, user_id, relation)
        )
    """)
    op.execute("CREATE INDEX idx_memberships_user ON case_memberships(user_id) WHERE revoked_at IS NULL")
    op.execute("CREATE INDEX idx_memberships_case ON case_memberships(case_id) WHERE revoked_at IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS case_memberships")
    op.execute("DROP TABLE IF EXISTS family_cases")
    op.execute("DROP TABLE IF EXISTS users")
