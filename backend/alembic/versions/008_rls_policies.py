"""008_rls_policies

Revision ID: 008
Revises: 007
Create Date: 2026-04-21 00:00:08
"""
from typing import Sequence, Union
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 建立 SECURITY DEFINER 函式：繞過 RLS 查詢 case_memberships
    # 避免 case_memberships policy 自我參照造成無限遞迴
    op.execute("""
        CREATE OR REPLACE FUNCTION get_user_case_ids(p_user_id UUID)
        RETURNS TABLE(case_id UUID)
        LANGUAGE SQL
        SECURITY DEFINER
        SET search_path = public
        AS $$
            SELECT case_id FROM case_memberships
            WHERE user_id = p_user_id
              AND revoked_at IS NULL
        $$
    """)

    # family_cases
    op.execute("ALTER TABLE family_cases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE family_cases FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY family_cases_isolation ON family_cases
            FOR ALL
            USING (
                id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # case_memberships：用 user_id 直接比對，避免遞迴
    # 使用者只能看到自己的成員資格列
    op.execute("ALTER TABLE case_memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE case_memberships FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY case_memberships_isolation ON case_memberships
            FOR ALL
            USING (
                user_id = current_setting('app.current_user_id', true)::UUID
            )
    """)

    # children
    op.execute("ALTER TABLE children ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE children FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY children_isolation ON children
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # custody_rules
    op.execute("ALTER TABLE custody_rules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE custody_rules FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY custody_rules_isolation ON custody_rules
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # custody_events
    op.execute("ALTER TABLE custody_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE custody_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY events_case_isolation ON custody_events
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # handover_records（透過 event 的 case_id）
    op.execute("ALTER TABLE handover_records ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE handover_records FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY handovers_isolation ON handover_records
            FOR ALL
            USING (
                event_id IN (
                    SELECT ce.id FROM custody_events ce
                    WHERE ce.case_id IN (
                        SELECT case_id FROM get_user_case_ids(
                            current_setting('app.current_user_id', true)::UUID
                        )
                    )
                    AND ce.deleted_at IS NULL
                )
            )
    """)

    # agent_sessions
    op.execute("ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_sessions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agent_sessions_isolation ON agent_sessions
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # agent_messages（透過 session 間接）
    op.execute("ALTER TABLE agent_messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_messages FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agent_messages_isolation ON agent_messages
            FOR ALL
            USING (
                session_id IN (
                    SELECT s.id FROM agent_sessions s
                    WHERE s.case_id IN (
                        SELECT case_id FROM get_user_case_ids(
                            current_setting('app.current_user_id', true)::UUID
                        )
                    )
                )
            )
    """)

    # reports
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reports FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY reports_isolation ON reports
            FOR ALL
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)

    # audit_log（只允許同 case 的成員 SELECT）
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_log_isolation ON audit_log
            FOR SELECT
            USING (
                case_id IN (
                    SELECT case_id FROM get_user_case_ids(
                        current_setting('app.current_user_id', true)::UUID
                    )
                )
            )
    """)
    # INSERT 由後端 BYPASSRLS 角色執行，一般使用者不可直接 INSERT
    op.execute("""
        CREATE POLICY audit_log_insert_deny ON audit_log
            FOR INSERT
            WITH CHECK (FALSE)
    """)


def downgrade() -> None:
    tables = [
        ("audit_log", ["audit_log_isolation", "audit_log_insert_deny"]),
        ("reports", ["reports_isolation"]),
        ("agent_messages", ["agent_messages_isolation"]),
        ("agent_sessions", ["agent_sessions_isolation"]),
        ("handover_records", ["handovers_isolation"]),
        ("custody_events", ["events_case_isolation"]),
        ("custody_rules", ["custody_rules_isolation"]),
        ("children", ["children_isolation"]),
        ("case_memberships", ["case_memberships_isolation"]),
        ("family_cases", ["family_cases_isolation"]),
    ]
    for table, policies in tables:
        for policy in policies:
            op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS get_user_case_ids(UUID)")
