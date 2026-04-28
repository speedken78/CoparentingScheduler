"""
Phase 1 端到端驗收劇本。
直接呼叫 service 層，不依賴 LLM API，GCS 上傳全程 mock。
所有 DB 呼叫使用 inline _make_db() 模式（避免 cross-event-loop 問題）。

執行：
    docker compose exec -T api pytest tests/e2e -v
"""
import calendar
import pytest
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


async def _make_db():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _seed_case(db: AsyncSession) -> SimpleNamespace:
    """建立最小化案件，回傳 SimpleNamespace(id, parent_a_id, agent_session_id)。"""
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()

    await db.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"e2e_{user_id}@test.com", "name": "E2E家長"})
    await db.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "E2E測試案件", "by": str(user_id)})
    await db.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})
    await db.commit()

    return SimpleNamespace(id=case_id, parent_a_id=user_id, agent_session_id=session_id)


def _make_ctx(case: SimpleNamespace):
    """直接建構 AgentContext，不呼叫 LLM。"""
    from app.agents.context import AgentContext
    return AgentContext(
        session_id=case.agent_session_id,
        case_id=case.id,
        speaker_user_id=case.parent_a_id,
        case_timezone="Asia/Taipei",
        active_rules=[],
        messages=[],
    )


# ── 劇本一：建規則 → 行事曆 → PDF → hash chain → 錨定 ─────────────────────

@pytest.mark.asyncio
async def test_scenario_1_single_parent_full_flow():
    """
    1. 建立「每週一三五」規則
    2. 查詢行事曆，確認事件存在
    3. 產生月報 PDF
    4. 驗證 hash chain valid
    5. 觸發錨定（mock GCS）
    """
    from app.services.schedule_service import create_rule
    from app.repositories.event_repo import EventRepository
    from app.services.report_service import generate_report
    from app.services.audit_anchor_service import run_anchor_job, verify_hash_chain

    db, engine = await _make_db()
    try:
        case = await _seed_case(db)
        ctx = _make_ctx(case)

        # Step 1: 建規則（每週一三五 07:30–17:30）
        rule_result = await create_rule(ctx, {
            "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
            "start_time": "07:30",
            "end_time": "17:30",
            "effective_from": date.today().isoformat(),
            "custodian": "speaker",
            "source": "unilateral",
        }, db)
        await db.commit()

        assert rule_result["expanded_events_count"] >= 1, \
            f"應有展開事件，實際：{rule_result}"

        # Step 2: 查行事曆
        events = await EventRepository(db).list_in_range(
            case.id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert len(events) >= 4, f"一個月內應有至少 4 個事件，實際 {len(events)}"
        assert all(e.status == "scheduled" for e in events)

        # Step 3: 產月報 PDF
        today = date.today()
        first_day = today.replace(day=1)
        last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])

        report = await generate_report(
            case_id=case.id,
            period_start=first_day,
            period_end=last_day,
            report_type="monthly",
            requesting_user_id=case.parent_a_id,
            db=db,
        )
        await db.commit()

        assert report.pdf_sha256
        assert len(report.pdf_sha256) == 64
        assert Path(report.pdf_gcs_path).exists(), f"PDF 應存在：{report.pdf_gcs_path}"

        # Step 4: 驗 hash chain
        chain_result = await verify_hash_chain(case.id, db)
        assert chain_result["valid"], f"Hash chain 不完整：{chain_result.get('error')}"
        assert chain_result["checked"] >= 2

        # Step 5: 錨定（mock GCS）
        with patch(
            "app.services.audit_anchor_service._upload_to_gcs",
            new_callable=AsyncMock,
            return_value="gs://coparenting-audit-anchors/anchors/e2e/001.txt",
        ):
            anchor_result = await run_anchor_job(db)
        await db.commit()

        assert anchor_result["status"] in ("anchored", "skipped")
        print(f"✓ 劇本一完成：{len(events)} 個事件，PDF {report.pdf_sha256[:8]}...")

    finally:
        await db.close()
        await engine.dispose()


# ── 劇本二：建規則 → 衝突偵測 ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_2_conflict_detection():
    """
    1. 建立「每週六」規則（產生事件）
    2. 嘗試在同一時段建立一次性事件
    3. create_event 回傳 conflict_blocked
    """
    from app.services.schedule_service import create_rule, create_event

    db, engine = await _make_db()
    try:
        case = await _seed_case(db)
        ctx = _make_ctx(case)

        # Step 1: 建週六規則
        await create_rule(ctx, {
            "rrule": "FREQ=WEEKLY;BYDAY=SA",
            "start_time": "09:00",
            "end_time": "18:00",
            "effective_from": date.today().isoformat(),
            "custodian": "speaker",
            "source": "unilateral",
        }, db)
        await db.commit()

        # Step 2: 找下一個週六
        today = date.today()
        days_until_saturday = (5 - today.weekday()) % 7 or 7
        next_saturday = today + timedelta(days=days_until_saturday)

        tz = ZoneInfo("Asia/Taipei")
        starts_at = datetime.combine(next_saturday, dtime(9, 0), tzinfo=tz)
        ends_at = datetime.combine(next_saturday, dtime(18, 0), tzinfo=tz)

        # Step 3: 嘗試建立衝突事件
        result = await create_event(ctx, {
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "custodian": "speaker",
            "notes": "E2E 衝突測試",
        }, db)

        assert result.get("status") == "conflict_blocked", \
            f"應被衝突偵測阻擋，實際：{result}"
        print(f"✓ 劇本二：衝突偵測正確攔截，status={result['status']}")

    finally:
        await db.close()
        await engine.dispose()


# ── 劇本三：建規則 → 撤銷 → 稽核軌跡 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_scenario_3_rule_revocation_audit_trail():
    """
    1. 建立「每週三」規則
    2. 提案撤銷
    3. 確認撤銷
    4. 驗 audit_log 有完整的 create → propose → revoke 軌跡
    5. 驗 scheduled 事件數量減少
    """
    from app.services.schedule_service import (
        create_rule, propose_revocation, confirm_revocation,
    )
    from app.repositories.event_repo import EventRepository
    from app.repositories.revocation_proposal_repo import RevocationProposalRepository
    from app.models.audit_log import AuditLog

    db, engine = await _make_db()
    try:
        case = await _seed_case(db)
        ctx = _make_ctx(case)

        # Step 1: 建規則
        rule_result = await create_rule(ctx, {
            "rrule": "FREQ=WEEKLY;BYDAY=WE",
            "start_time": "07:30",
            "end_time": "17:30",
            "effective_from": date.today().isoformat(),
            "custodian": "speaker",
            "source": "unilateral",
        }, db)
        await db.commit()
        assert rule_result["expanded_events_count"] > 0

        # 確認有事件
        events_before = await EventRepository(db).list_in_range(
            case.id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert len(events_before) > 0

        # Step 2: 提案撤銷（hint 含「週三」，_find_rule_by_hint 靠此配對）
        proposal_result = await propose_revocation(ctx, {
            "rule_hint": "每週三的規則",
            "revocation_reason": "E2E 測試撤銷",
        }, db)
        await db.commit()
        assert proposal_result["rule_matched"] is True, \
            f"應配對到規則，實際：{proposal_result}"

        # Step 3: 確認撤銷
        proposals = await RevocationProposalRepository(db).list_pending(case.id)
        assert len(proposals) >= 1

        confirm_result = await confirm_revocation(proposals[0].id, case.parent_a_id, db)
        await db.commit()
        assert confirm_result["status"] == "confirmed"

        # Step 4: 驗事件被軟刪除
        events_after = await EventRepository(db).list_in_range(
            case.id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert len(events_after) < len(events_before), \
            f"撤銷後應減少事件，before={len(events_before)} after={len(events_after)}"

        # Step 5: 驗 audit_log 軌跡
        audit_result = await db.execute(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.id.asc())
        )
        logs = list(audit_result.scalars().all())
        actions = [log.action for log in logs]

        assert "create_custody_rule" in actions, \
            f"應有 create_custody_rule，實際：{actions}"
        assert "propose_revocation" in actions, \
            f"應有 propose_revocation，實際：{actions}"
        assert "revoke_custody_rule" in actions, \
            f"應有 revoke_custody_rule，實際：{actions}"

        print(f"✓ 劇本三：稽核軌跡完整，共 {len(logs)} 筆 audit_log，actions={actions}")

    finally:
        await db.close()
        await engine.dispose()
