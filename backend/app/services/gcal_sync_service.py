import asyncio
import time
from datetime import datetime, timezone as dt_tz
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custody_event import CustodyEvent
from app.models.user import User
from app.models.gcal_sync_log import GCalSyncLog
from app.services.integrations.google_calendar import (
    GCalClientProtocol, GCalEventInput, build_gcal_client,
)

GCAL_TIMEOUT_SECONDS = 5
CALENDAR_ID = "primary"


def build_event_summary(
    custodian_label: str,
    child_display_name: str | None,
    case_name: str,
) -> str:
    child_part = child_display_name or "全部小孩"
    return f"[共親職] {child_part} - {custodian_label}監護"


async def sync_event_to_gcal(
    event: CustodyEvent,
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,
) -> dict:
    """
    把單一 custody_event 同步到指定 user 的 GCal。
    回傳 {"status": "success"|"failed"|"skipped", "gcal_event_id": str|None}
    """
    start_ms = time.monotonic()

    if not user.gcal_scope_granted or not user.google_refresh_token_enc:
        await _log_sync(db, event.id, user.id, "insert", "skipped",
                        error_message="gcal_scope_not_granted")
        return {"status": "skipped", "gcal_event_id": None}

    if gcal_client is None:
        gcal_client = build_gcal_client(user.google_refresh_token_enc)

    from app.models.case import FamilyCase
    from app.models.child import Child
    case = await db.get(FamilyCase, event.case_id)
    child = await db.get(Child, event.child_id) if event.child_id else None

    custodian_label = "我" if str(event.custodian_id) == str(user.id) else "對方"

    gcal_input = GCalEventInput(
        summary=build_event_summary(
            custodian_label=custodian_label,
            child_display_name=child.display_name if child else None,
            case_name=case.case_name if case else "",
        ),
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        description=(
            f"案件：{case.case_name if case else ''}\n"
            f"備註：{event.notes or ''}\n"
            f"地點：{event.handover_location or ''}\n"
            f"（由共親職排程 App 自動同步）"
        ),
        location=event.handover_location or "",
        color_id="1" if custodian_label == "我" else "2",
    )

    try:
        if event.gcal_event_id:
            result = await asyncio.wait_for(
                gcal_client.update_event(CALENDAR_ID, event.gcal_event_id, gcal_input),
                timeout=GCAL_TIMEOUT_SECONDS,
            )
            action = "update"
        else:
            result = await asyncio.wait_for(
                gcal_client.insert_event(CALENDAR_ID, gcal_input),
                timeout=GCAL_TIMEOUT_SECONDS,
            )
            action = "insert"

        event.gcal_event_id = result.gcal_event_id
        event.gcal_synced_at = datetime.now(dt_tz.utc)
        await db.flush()

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, action, "success",
                        gcal_event_id=result.gcal_event_id,
                        duration_ms=duration_ms)

        return {"status": "success", "gcal_event_id": result.gcal_event_id}

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, "insert", "failed",
                        error_message="timeout", duration_ms=duration_ms)
        return {"status": "failed", "gcal_event_id": None}

    except Exception as e:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, "insert", "failed",
                        error_message=str(e)[:500], duration_ms=duration_ms)
        return {"status": "failed", "gcal_event_id": None}


async def sync_events_batch(
    events: list[CustodyEvent],
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,
) -> dict:
    counts = {"success": 0, "failed": 0, "skipped": 0}
    for event in events:
        result = await sync_event_to_gcal(event, user, db, gcal_client)
        counts[result["status"]] += 1
    return counts


async def delete_gcal_event(
    event: CustodyEvent,
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,
) -> dict:
    if not event.gcal_event_id:
        return {"status": "skipped", "reason": "no_gcal_event_id"}

    if not user.gcal_scope_granted or not user.google_refresh_token_enc:
        return {"status": "skipped", "reason": "gcal_scope_not_granted"}

    if gcal_client is None:
        gcal_client = build_gcal_client(user.google_refresh_token_enc)

    try:
        await asyncio.wait_for(
            gcal_client.delete_event(CALENDAR_ID, event.gcal_event_id),
            timeout=GCAL_TIMEOUT_SECONDS,
        )
        await _log_sync(db, event.id, user.id, "delete", "success",
                        gcal_event_id=event.gcal_event_id)
        return {"status": "success"}

    except Exception as e:
        await _log_sync(db, event.id, user.id, "delete", "failed",
                        error_message=str(e)[:500])
        return {"status": "failed", "error": str(e)}


async def _log_sync(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
    action: str,
    status: str,
    gcal_event_id: str | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    log = GCalSyncLog(
        entity_type="custody_event",
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        status=status,
        gcal_event_id=gcal_event_id,
        error_message=error_message,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.flush()
