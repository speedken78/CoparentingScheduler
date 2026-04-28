"""003_children_and_rules

Revision ID: 003
Revises: 002
Create Date: 2026-04-21 00:00:03
"""
from typing import Sequence, Union
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE children (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id         UUID NOT NULL REFERENCES family_cases(id),
            display_name    TEXT NOT NULL,
            birth_date      DATE NOT NULL,
            notes           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at      TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE custody_rules (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id           UUID NOT NULL REFERENCES family_cases(id),
            child_id          UUID REFERENCES children(id),
            custodian_id      UUID NOT NULL REFERENCES users(id),
            rule_type         TEXT NOT NULL CHECK (rule_type IN
                                ('weekly','biweekly','monthly_nth_weekday','custom_rrule')),
            rrule             TEXT NOT NULL,
            start_time        TIME NOT NULL,
            end_time          TIME NOT NULL,
            effective_from    DATE NOT NULL,
            effective_until   DATE,
            priority          INT NOT NULL DEFAULT 100,
            source            TEXT NOT NULL CHECK (source IN
                                ('court_order','mutual_agreement','unilateral')),
            source_document   TEXT,
            notes             TEXT,
            created_by        UUID NOT NULL REFERENCES users(id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            revoked_at        TIMESTAMPTZ,
            revoked_by        UUID REFERENCES users(id),
            revoked_reason    TEXT
        )
    """)
    op.execute("""
        CREATE INDEX idx_rules_case_active ON custody_rules(case_id, effective_from, effective_until)
            WHERE revoked_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS custody_rules")
    op.execute("DROP TABLE IF EXISTS children")
