import asyncio
from datetime import datetime, timezone as dt_tz
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditAnchor, AuditLog
from app.config import settings


async def run_anchor_job(db: AsyncSession) -> dict:
    """
    把當前 audit_log 的最新雜湊錨定到 GCS Object Lock bucket。
    冪等：若最新一筆 audit_log 已錨定，直接回傳 skipped。
    """
    result = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    last = result.one_or_none()
    if not last:
        return {"status": "skipped", "reason": "no_audit_log_entries"}

    last_audit_id, last_row_hash = last

    exists = await db.execute(
        select(AuditAnchor.id)
        .where(AuditAnchor.last_audit_id == last_audit_id)
        .limit(1)
    )
    if exists.scalar_one_or_none():
        return {
            "status": "skipped",
            "reason": "already_anchored",
            "last_audit_id": last_audit_id,
            "last_row_hash": last_row_hash,
        }

    anchored_at = datetime.now(dt_tz.utc)
    content = (
        f"audit_log_id={last_audit_id}\n"
        f"row_hash={last_row_hash}\n"
        f"anchored_at={anchored_at.isoformat()}\n"
    )
    content_bytes = content.encode("utf-8")

    gcs_path = (
        f"anchors/"
        f"{anchored_at:%Y/%m/%d}/"
        f"{last_audit_id}_{anchored_at:%H%M%S}.txt"
    )
    try:
        anchor_proof = await _upload_to_gcs(
            bucket_name=settings.GCS_BUCKET_AUDIT,
            path=gcs_path,
            content=content_bytes,
        )
    except Exception as e:
        return {
            "status": "failed",
            "last_audit_id": last_audit_id,
            "last_row_hash": last_row_hash,
            "error": str(e)[:500],
        }

    anchor = AuditAnchor(
        anchored_at=anchored_at,
        last_audit_id=last_audit_id,
        last_row_hash=last_row_hash,
        anchor_target="gcs",
        anchor_proof=anchor_proof,
    )
    db.add(anchor)
    await db.flush()

    return {
        "status": "anchored",
        "last_audit_id": last_audit_id,
        "last_row_hash": last_row_hash,
        "anchor_proof": anchor_proof,
    }


async def _upload_to_gcs(bucket_name: str, path: str, content: bytes) -> str:
    """上傳到 GCS，回傳 gs:// 路徑。"""
    from google.cloud import storage as gcs

    def _upload():
        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        blob.upload_from_string(content, content_type="text/plain; charset=utf-8")
        return f"gs://{bucket_name}/{path}"

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _upload)


async def verify_hash_chain(
    case_id: UUID,
    db: AsyncSession,
    limit: int = 100,
) -> dict:
    """
    驗證指定 case 的 audit_log hash chain 完整性。
    """
    from app.utils.hash_chain import compute_row_hash

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.asc())
        .limit(limit)
    )
    logs = list(result.scalars().all())

    prev_hash = None
    for log in logs:
        row_data = {
            "case_id": log.case_id,
            "actor_id": log.actor_id,
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "before_state": log.before_state,
            "after_state": log.after_state,
            "triggered_by": log.triggered_by,
            "occurred_at": log.occurred_at,
        }
        expected_hash = compute_row_hash(row_data, prev_hash)
        if expected_hash != log.row_hash:
            return {
                "valid": False,
                "checked": logs.index(log),
                "first_invalid_id": log.id,
                "error": f"Hash mismatch at audit_log.id={log.id}",
            }
        prev_hash = log.row_hash

    return {"valid": True, "checked": len(logs), "first_invalid_id": None}
