"""007_reports

Revision ID: 007
Revises: 006
Create Date: 2026-04-21 00:00:07
"""
from typing import Sequence, Union
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE reports (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id           UUID NOT NULL REFERENCES family_cases(id),
            report_type       TEXT NOT NULL CHECK (report_type IN
                                ('monthly','custom_range','dispute','full_history')),
            period_start      DATE NOT NULL,
            period_end        DATE NOT NULL,
            generated_by      UUID NOT NULL REFERENCES users(id),
            generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            pdf_gcs_path      TEXT NOT NULL,
            pdf_sha256        TEXT NOT NULL,
            last_audit_id     BIGINT NOT NULL,
            last_audit_hash   TEXT NOT NULL,
            anchor_id         BIGINT REFERENCES audit_anchors(id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reports")
