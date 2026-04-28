"""013: reports index and grant

Revision ID: 013
Revises: 012
Create Date: 2026-04-24 00:00:13

reports 表已在 migration 007 建立，RLS 在 008，GRANT 在 009。
本 migration 補加缺少的 index，並確保表存在（IF NOT EXISTS 保護）。
"""
from typing import Sequence, Union
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id         UUID NOT NULL REFERENCES family_cases(id),
            report_type     TEXT NOT NULL
                            CHECK (report_type IN
                                ('monthly','custom_range','dispute','full_history')),
            period_start    DATE NOT NULL,
            period_end      DATE NOT NULL,
            generated_by    UUID NOT NULL REFERENCES users(id),
            generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            pdf_gcs_path    TEXT NOT NULL,
            pdf_sha256      TEXT NOT NULL,
            last_audit_id   BIGINT NOT NULL,
            last_audit_hash TEXT NOT NULL,
            anchor_id       BIGINT REFERENCES audit_anchors(id)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_reports_case
            ON reports(case_id, generated_at DESC)
    """)

    op.execute("GRANT SELECT, INSERT ON reports TO app_role")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reports_case")
    op.execute("DROP TABLE IF EXISTS reports CASCADE")
