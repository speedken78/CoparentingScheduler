"""Integration tests for schedule_service — requires running PostgreSQL."""
import pytest
from datetime import date, datetime, timezone, timedelta
from uuid import uuid4
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.schedule_service import create_rule, create_event, confirm_revocation
from app.agents.context import AgentContext
from app.models.audit_log import AuditLog
from app.models.custody_event import CustodyEvent
from app.repositories.event_repo import EventRepository
from app.repositories.rule_repo import RuleRepository
from app.repositories.revocation_proposal_repo import RevocationProposalRepository


async def _make_db() -> tuple[AsyncSession, object]:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _seed_case(db: AsyncSession):
    """在 db 中建立最小化案件，回傳 (case_id, user_id, session_id)。"""
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()
    await db.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"sched_{user_id}@test.com", "name": "排程測試"})
    await db.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "整合測試案件", "by": str(user_id)})
    await db.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})
    await db.commit()
    return case_id, user_id, session_id


def _ctx(case_id, user_id, session_id) -> AgentContext:
    return AgentContext(
        session_id=session_id,
        case_id=case_id,
        speaker_user_id=user_id,
        case_timezone="Asia/Taipei",
        active_rules=[],
        messages=[],
    )


@pytest.mark.asyncio
async def test_create_rule_expands_events():
    """建立規則後，custody_events 有對應展開，且 audit_log 記錄正確。"""
    db, engine = await _make_db()
    try:
        case_id, user_id, session_id = await _seed_case(db)
        ctx = _ctx(case_id, user_id, session_id)
        tool_input = {
            "custodian": "speaker",
            "child_scope": "all_children",
            "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
            "start_time": "07:30",
            "end_time": "17:30",
            "effective_from": date.today().isoformat(),
            "source": "unilateral",
            "confidence": 0.95,
            "reasoning": "整合測試：每週一三五",
        }

        result = await create_rule(ctx, tool_input, db)
        await db.commit()

        assert result["expanded_events_count"] > 0

        from sqlalchemy import select as sa_select
        events_result = await db.execute(
            sa_select(CustodyEvent).where(
                CustodyEvent.rule_id == result["id"],
                CustodyEvent.deleted_at.is_(None),
            )
        )
        events = list(events_result.scalars().all())
        assert len(events) == result["expanded_events_count"]

        log_result = await db.execute(
            select(AuditLog).where(
                AuditLog.action == "create_custody_rule",
                AuditLog.entity_id == result["id"],
            )
        )
        logs = list(log_result.scalars().all())
        assert len(logs) == 1
        assert logs[0].triggered_by == "agent"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_one_time_event_conflict_blocked():
    """在已有事件的時段建立單一事件，應被擋下。"""
    db, engine = await _make_db()
    try:
        case_id, user_id, session_id = await _seed_case(db)

        # 預先插入一筆事件
        event_starts = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
        event_ends = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)
        await db.execute(text(
            "INSERT INTO custody_events "
            "(id, case_id, custodian_id, starts_at, ends_at, status, created_by) "
            "VALUES (:id, :cid, :uid, :s, :e, 'scheduled', :uid)"
        ), {
            "id": str(uuid4()), "cid": str(case_id), "uid": str(user_id),
            "s": event_starts, "e": event_ends,
        })
        await db.commit()

        ctx = _ctx(case_id, user_id, session_id)
        tool_input = {
            "custodian": "speaker",
            "child_scope": "all_children",
            "starts_at": event_starts.isoformat(),
            "ends_at": event_ends.isoformat(),
            "confidence": 0.95,
            "reasoning": "衝突測試",
        }
        result = await create_event(ctx, tool_input, db)
        assert result["status"] == "conflict_blocked"
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_revocation_deletes_future_scheduled_only():
    """
    撤銷規則後：
    - effective_from 之後的 scheduled 事件被軟刪除
    - 已 completed 的事件保留
    """
    db, engine = await _make_db()
    try:
        case_id, user_id, session_id = await _seed_case(db)
        ctx = _ctx(case_id, user_id, session_id)

        # 1. 建立規則 + 展開事件
        create_result = await create_rule(ctx, {
            "custodian": "speaker",
            "child_scope": "all_children",
            "rrule": "FREQ=WEEKLY;BYDAY=TU",
            "start_time": "09:00",
            "end_time": "18:00",
            "effective_from": date.today().isoformat(),
            "source": "unilateral",
            "confidence": 0.95,
            "reasoning": "撤銷測試用規則",
        }, db)
        await db.commit()
        rule_id = create_result["id"]
        initial_count = create_result["expanded_events_count"]
        assert initial_count > 0

        # 2. 把第一個事件標記為 completed（不應被刪除）
        events = await EventRepository(db).list_in_range(
            case_id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=180),
        )
        first_event_id = events[0].id
        await db.execute(text(
            "UPDATE custody_events SET status='completed' WHERE id=:id"
        ), {"id": str(first_event_id)})
        await db.commit()

        # 3. 建立撤銷提案
        proposal_repo = RevocationProposalRepository(db)
        proposal = await proposal_repo.insert({
            "case_id": case_id,
            "rule_id": rule_id,
            "rule_hint": "週二",
            "revocation_reason": "測試撤銷",
            "effective_from": date.today(),
            "proposed_by": user_id,
            "agent_session_id": session_id,
        })
        await db.commit()

        # 4. 確認撤銷
        result = await confirm_revocation(proposal.id, user_id, db)
        await db.commit()

        assert result["status"] == "confirmed"
        # completed 的事件不被刪除，所以 deleted_count < initial_count
        assert result["deleted_events_count"] < initial_count

        # 5. 確認 completed 事件仍存在
        check = await db.execute(
            select(CustodyEvent).where(
                CustodyEvent.id == first_event_id,
                CustodyEvent.deleted_at.is_(None),
            )
        )
        assert check.scalar_one_or_none() is not None, "completed 事件不應被刪除"
    finally:
        await db.close()
        await engine.dispose()
