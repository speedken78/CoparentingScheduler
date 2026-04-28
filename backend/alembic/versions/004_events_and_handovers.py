"""004_events_and_handovers

Revision ID: 004
Revises: 003
Create Date: 2026-04-21 00:00:04
"""
from typing import Sequence, Union
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE custody_events (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id           UUID NOT NULL REFERENCES family_cases(id),
            child_id          UUID REFERENCES children(id),
            custodian_id      UUID NOT NULL REFERENCES users(id),
            rule_id           UUID REFERENCES custody_rules(id),
            starts_at         TIMESTAMPTZ NOT NULL,
            ends_at           TIMESTAMPTZ NOT NULL,
            status            TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN
                                ('scheduled','confirmed','in_progress','completed',
                                 'missed','disputed','cancelled')),
            handover_location TEXT,
            notes             TEXT,
            gcal_event_id     TEXT,
            gcal_synced_at    TIMESTAMPTZ,
            created_by        UUID NOT NULL REFERENCES users(id),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deleted_at        TIMESTAMPTZ,
            CHECK (ends_at > starts_at)
        )
    """)
    op.execute("""
        CREATE INDEX idx_events_case_time ON custody_events(case_id, starts_at, ends_at)
            WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE INDEX idx_events_custodian_time ON custody_events(custodian_id, starts_at)
            WHERE deleted_at IS NULL
    """)
    op.execute("""
        CREATE INDEX idx_events_gcal ON custody_events(gcal_event_id)
            WHERE gcal_event_id IS NOT NULL
    """)
    op.execute("""
        ALTER TABLE custody_events
            ADD CONSTRAINT custody_events_no_overlap
            EXCLUDE USING gist (
                custodian_id WITH =,
                child_id WITH =,
                tstzrange(starts_at, ends_at, '[)') WITH &&
            ) WHERE (deleted_at IS NULL AND status != 'cancelled')
    """)

    op.execute("""
        CREATE TABLE handover_records (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id               UUID NOT NULL REFERENCES custody_events(id),
            action                 TEXT NOT NULL CHECK (action IN ('pickup','dropoff')),
            performed_by           UUID NOT NULL REFERENCES users(id),
            performed_at           TIMESTAMPTZ NOT NULL,
            location_lat           NUMERIC(8,3),
            location_lng           NUMERIC(8,3),
            location_accuracy_m    INT,
            photo_gcs_path         TEXT,
            counterparty_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            counterparty_confirmed_at TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX idx_handovers_event ON handover_records(event_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS handover_records")
    op.execute("ALTER TABLE custody_events DROP CONSTRAINT IF EXISTS custody_events_no_overlap")
    op.execute("DROP TABLE IF EXISTS custody_events")
