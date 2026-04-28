"""011: revocation proposals

Revision ID: 011
Revises: 010
Create Date: 2026-04-24 00:00:11
"""
from typing import Sequence, Union
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE revocation_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL REFERENCES family_cases(id),
            rule_id UUID REFERENCES custody_rules(id),
            rule_hint TEXT NOT NULL,
            revocation_reason TEXT NOT NULL,
            effective_from DATE NOT NULL,
            proposed_by UUID NOT NULL REFERENCES users(id),
            agent_session_id UUID REFERENCES agent_sessions(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','confirmed','rejected','expired')),
            confirmed_at TIMESTAMPTZ,
            confirmed_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
        )
    """)

    op.execute("""
        CREATE INDEX idx_revocation_case_status
            ON revocation_proposals(case_id, status)
    """)

    op.execute("ALTER TABLE revocation_proposals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE revocation_proposals FORCE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY revocation_proposals_case_isolation
            ON revocation_proposals
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON revocation_proposals TO app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS revocation_proposals CASCADE")
