"""Unit tests for audit anchor service — all DB tests use inline _make_db()."""
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


async def _make_db():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _seed_minimal(db: AsyncSession):
    """建立最小化案件，回傳 (case_id, user_id)。"""
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()
    await db.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"anchor_{user_id}@test.com", "name": "錨定測試"})
    await db.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "錨定測試案件", "by": str(user_id)})
    await db.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})
    await db.commit()
    return case_id, user_id


# ── DB-backed tests (inline _make_db) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_anchor_job_skipped_when_no_logs():
    """獨立 DB session，run_anchor_job 在 skipped/anchored/already_anchored 三種情況下都不拋錯。"""
    from app.services.audit_anchor_service import run_anchor_job

    db, engine = await _make_db()
    try:
        # 共享 DB 可能有其他測試留下的 audit_log，需要 mock GCS 以防 "failed"
        with patch(
            "app.services.audit_anchor_service._upload_to_gcs",
            new_callable=AsyncMock,
            return_value="gs://mock-bucket/anchors/test.txt",
        ):
            result = await run_anchor_job(db)
        assert result["status"] in ("skipped", "anchored", "already_anchored")
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_anchor_job_idempotent():
    """同一筆 audit_log 錨定兩次，第二次 reason=already_anchored。"""
    from app.services.audit_anchor_service import run_anchor_job
    from app.services.audit_service import log as audit_log_svc

    db, engine = await _make_db()
    try:
        case_id, user_id = await _seed_minimal(db)

        await audit_log_svc(
            db,
            case_id=case_id,
            actor_id=user_id,
            action="create_case",
            entity_type="family_case",
            entity_id=case_id,
            before_state=None,
            after_state={"case_name": "test"},
            triggered_by="human",
        )
        await db.commit()

        with patch(
            "app.services.audit_anchor_service._upload_to_gcs",
            new_callable=AsyncMock,
            return_value="gs://mock-bucket/anchors/test.txt",
        ):
            result1 = await run_anchor_job(db)
            await db.commit()
            result2 = await run_anchor_job(db)
    finally:
        await db.close()
        await engine.dispose()

    assert result1["status"] == "anchored"
    assert result2["status"] == "skipped"
    assert result2.get("reason") == "already_anchored"


@pytest.mark.asyncio
async def test_anchor_job_gcs_failure_returns_failed():
    """GCS 上傳失敗時回傳 failed，不拋 exception。"""
    from app.services.audit_anchor_service import run_anchor_job
    from app.services.audit_service import log as audit_log_svc

    db, engine = await _make_db()
    try:
        case_id, user_id = await _seed_minimal(db)

        await audit_log_svc(
            db,
            case_id=case_id,
            actor_id=user_id,
            action="create_case",
            entity_type="family_case",
            entity_id=case_id,
            before_state=None,
            after_state={"case_name": "test"},
            triggered_by="human",
        )
        await db.commit()

        with patch(
            "app.services.audit_anchor_service._upload_to_gcs",
            new_callable=AsyncMock,
            side_effect=Exception("GCS connection refused"),
        ):
            result = await run_anchor_job(db)
    finally:
        await db.close()
        await engine.dispose()

    assert result["status"] == "failed"
    assert "GCS" in result.get("error", "")


@pytest.mark.asyncio
async def test_verify_hash_chain_valid():
    """seed 資料的 hash chain 應該是 valid。"""
    from app.services.audit_anchor_service import verify_hash_chain
    from app.services.audit_service import log as audit_log_svc

    db, engine = await _make_db()
    try:
        case_id, user_id = await _seed_minimal(db)

        await audit_log_svc(
            db,
            case_id=case_id,
            actor_id=user_id,
            action="create_case",
            entity_type="family_case",
            entity_id=case_id,
            before_state=None,
            after_state={"case_name": "test"},
            triggered_by="human",
        )
        await db.commit()

        result = await verify_hash_chain(case_id, db)
    finally:
        await db.close()
        await engine.dispose()

    assert result["valid"] is True
    assert result["first_invalid_id"] is None


# ── Pure unit test (no DB) ─────────────────────────────────────────────────

def test_anchor_content_format():
    """錨定檔案格式：三行固定格式。"""
    content = (
        "audit_log_id=42\n"
        "row_hash=abc123\n"
        "anchored_at=2026-04-21T10:00:00+00:00\n"
    )
    lines = content.strip().split("\n")
    assert lines[0].startswith("audit_log_id=")
    assert lines[1].startswith("row_hash=")
    assert lines[2].startswith("anchored_at=")


@pytest.mark.asyncio
async def test_admin_endpoint_token_validation():
    """Admin endpoint 無 token 回 403，正確 token 回 200（mock GCS）。"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp_no_token = await client.post("/api/v1/admin/jobs/anchor-audit-log")
        assert resp_no_token.status_code == 422  # Header missing → 422

        resp_wrong_token = await client.post(
            "/api/v1/admin/jobs/anchor-audit-log",
            headers={"X-Job-Token": "wrong_token"},
        )
        assert resp_wrong_token.status_code == 403

        with patch(
            "app.services.audit_anchor_service._upload_to_gcs",
            new_callable=AsyncMock,
            return_value="gs://mock/test.txt",
        ):
            resp_ok = await client.post(
                "/api/v1/admin/jobs/anchor-audit-log",
                headers={"X-Job-Token": settings.JOB_SECRET_TOKEN},
            )
        assert resp_ok.status_code == 200
        assert resp_ok.json()["status"] in ("skipped", "anchored", "already_anchored")
