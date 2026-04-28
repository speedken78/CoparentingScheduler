"""012: gcal sync log

Revision ID: 012
Revises: 011
Create Date: 2026-04-24 00:00:12
"""
from typing import Sequence, Union
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE gcal_sync_log (
            id          BIGSERIAL PRIMARY KEY,
            entity_type TEXT NOT NULL
                        CHECK (entity_type IN ('custody_event', 'custody_rule')),
            entity_id   UUID NOT NULL,
            user_id     UUID NOT NULL REFERENCES users(id),
            action      TEXT NOT NULL
                        CHECK (action IN ('insert', 'update', 'delete')),
            status      TEXT NOT NULL
                        CHECK (status IN ('success', 'failed', 'skipped')),
            gcal_event_id TEXT,
            error_message TEXT,
            duration_ms INT,
            synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX idx_gcal_sync_entity
            ON gcal_sync_log(entity_type, entity_id, synced_at DESC)
    """)

    op.execute("""
        CREATE INDEX idx_gcal_sync_failed
            ON gcal_sync_log(status, synced_at DESC)
            WHERE status = 'failed'
    """)

    op.execute("GRANT SELECT, INSERT ON gcal_sync_log TO app_role")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gcal_sync_log;")
