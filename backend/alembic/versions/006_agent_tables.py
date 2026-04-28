"""006_agent_tables

Revision ID: 006
Revises: 005
Create Date: 2026-04-21 00:00:06
"""
from typing import Sequence, Union
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE agent_sessions (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id           UUID NOT NULL REFERENCES family_cases(id),
            user_id           UUID NOT NULL REFERENCES users(id),
            started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_active_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                                ('active','completed','abandoned'))
        )
    """)

    op.execute("""
        CREATE TABLE agent_messages (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id        UUID NOT NULL REFERENCES agent_sessions(id),
            role              TEXT NOT NULL CHECK (role IN ('user','assistant','tool_result')),
            content           JSONB NOT NULL,
            tool_use_id       TEXT,
            tool_name         TEXT,
            model             TEXT,
            input_tokens      INT,
            output_tokens     INT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_agent_msgs_session ON agent_messages(session_id, created_at)")

    # 補上 audit_log.agent_session_id 的 FK constraint
    op.execute("""
        ALTER TABLE audit_log
            ADD CONSTRAINT fk_audit_log_agent_session
            FOREIGN KEY (agent_session_id) REFERENCES agent_sessions(id)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS fk_audit_log_agent_session")
    op.execute("DROP TABLE IF EXISTS agent_messages")
    op.execute("DROP TABLE IF EXISTS agent_sessions")
