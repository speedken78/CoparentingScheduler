"""005_audit_log

Revision ID: 005
Revises: 004
Create Date: 2026-04-21 00:00:05
"""
from typing import Sequence, Union
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE audit_log (
            id              BIGSERIAL PRIMARY KEY,
            case_id         UUID NOT NULL,
            actor_id        UUID NOT NULL,
            action          TEXT NOT NULL,
            entity_type     TEXT NOT NULL,
            entity_id       UUID NOT NULL,
            before_state    JSONB,
            after_state     JSONB,
            triggered_by    TEXT NOT NULL DEFAULT 'human'
                            CHECK (triggered_by IN ('human','agent','system')),
            agent_session_id UUID,
            ip_address      INET,
            user_agent      TEXT,
            device_id       TEXT,
            occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            prev_hash       TEXT,
            row_hash        TEXT NOT NULL
        )
    """)
    op.execute("CREATE INDEX idx_audit_case_time ON audit_log(case_id, occurred_at)")
    op.execute("CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id)")

    # 防篡改 rules
    op.execute("CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING")
    op.execute("CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING")

    op.execute("""
        CREATE TABLE audit_anchors (
            id              BIGSERIAL PRIMARY KEY,
            anchored_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_audit_id   BIGINT NOT NULL,
            last_row_hash   TEXT NOT NULL,
            anchor_target   TEXT NOT NULL CHECK (anchor_target IN ('gcs','tsa')),
            anchor_proof    TEXT NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_anchors_audit_id ON audit_anchors(last_audit_id)")

    # 補上 audit_log 的 agent_session_id FK（在 006 建立 agent_sessions 後會 retroactively 生效）
    # 注意：agent_sessions 在 006 建立，所以此 FK 在 006 後才加


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_anchors")
    op.execute("DROP RULE IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP RULE IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP TABLE IF EXISTS audit_log")
