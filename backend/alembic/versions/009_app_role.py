"""009: create app_role with bypassrls, no ddl

Revision ID: 009
Revises: 008
Create Date: 2026-04-22 00:00:09
"""
from typing import Sequence, Union
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
                CREATE ROLE app_role WITH
                    NOLOGIN
                    NOINHERIT
                    BYPASSRLS
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE;
            END IF;
        END
        $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user WITH
                    LOGIN
                    NOINHERIT
                    PASSWORD 'PLACEHOLDER_CHANGE_IN_ENV'
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE;
            END IF;
        END
        $$;
    """)

    op.execute("GRANT app_role TO app_user")

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_role")

    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role")

    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role
    """)

    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO app_role
    """)

    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM app_role")


def downgrade() -> None:
    op.execute("REASSIGN OWNED BY app_user TO postgres")
    op.execute("DROP ROLE IF EXISTS app_user")
    op.execute("DROP ROLE IF EXISTS app_role")
