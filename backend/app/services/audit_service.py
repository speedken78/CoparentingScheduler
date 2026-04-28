from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.utils.hash_chain import compute_row_hash


async def log(
    db: AsyncSession,
    *,
    case_id: Optional[UUID],
    actor_id: UUID,
    action: str,
    entity_type: str,
    entity_id: UUID,
    before_state: Optional[dict] = None,
    after_state: Optional[dict] = None,
    triggered_by: Literal["human", "agent", "system"] = "human",
    agent_session_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    device_id: Optional[str] = None,
) -> Optional[AuditLog]:
    """Write one audit_log row with hash chain. Must be called within an open transaction."""
    if case_id is None:
        # user_login and other user-scoped actions have no case context — skip DB write
        return None

    occurred_at = datetime.now(timezone.utc)

    # Acquire advisory lock on case_id to serialize concurrent audit_log inserts
    # for the same case — avoids needing UPDATE privilege (which is revoked from app_role).
    lock_key = abs(hash(str(case_id))) % (2**31)
    await db.execute(text(f"SELECT pg_advisory_xact_lock({lock_key})"))

    # Fetch previous hash for this case
    prev_result = await db.execute(
        select(AuditLog.row_hash)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    prev_hash = prev_result.scalar_one_or_none()

    row_data = {
        "case_id": case_id,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "before_state": before_state,
        "after_state": after_state,
        "triggered_by": triggered_by,
        "agent_session_id": agent_session_id,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "device_id": device_id,
        "occurred_at": occurred_at,
        "prev_hash": prev_hash,
    }
    row_data["row_hash"] = compute_row_hash(row_data, prev_hash)

    entry = AuditLog(**row_data)
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry
