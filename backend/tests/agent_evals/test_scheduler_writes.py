"""
Agent Eval（寫入驗證）：驗證 LLM 解析後真的寫入 DB。
執行方式：
    docker compose exec -T api pytest tests/agent_evals/test_scheduler_writes.py -v -m eval
    （需要 Vertex AI 憑證：Cloud Run ADC 或本地 gcloud auth application-default login）
"""
import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from types import SimpleNamespace
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.services.agent_service import handle_message
from app.repositories.rule_repo import RuleRepository
from app.repositories.event_repo import EventRepository

pytestmark = pytest.mark.eval


async def _make_db():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _setup_seeded_case():
    """建立最小化案件並 commit，回傳 SimpleNamespace。"""
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()
    db, engine = await _make_db()
    try:
        await db.execute(text(
            "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
        ), {"id": str(user_id), "email": f"eval_{user_id}@test.com", "name": "Eval家長"})

        await db.execute(text(
            "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
            "VALUES (:id, :name, 'joint', :by)"
        ), {"id": str(case_id), "name": "Eval測試案件", "by": str(user_id)})

        await db.execute(text(
            "INSERT INTO case_memberships (id, case_id, user_id, relation) "
            "VALUES (:id, :cid, :uid, 'parent_a')"
        ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})

        await db.execute(text(
            "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
        ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})

        await db.commit()
    finally:
        await db.close()
        await engine.dispose()

    return SimpleNamespace(id=case_id, parent_a_id=user_id, agent_session_id=session_id)


@pytest.mark.asyncio
async def test_B1_writes_to_db():
    """B1 升級：驗證 LLM 解析後，custody_rules 和 custody_events 真的有資料。"""
    seeded_case = await _setup_seeded_case()
    db, engine = await _make_db()
    try:
        result = await handle_message(
            case_id=seeded_case.id,
            user_id=seeded_case.parent_a_id,
            user_text="我每週一、三、五 07:30 到 17:30 帶小孩",
            session_id=None,
            db=db,
        )
        await db.commit()

        tool_names = [a["tool"] for a in result["actions_taken"]]
        assert "create_recurring_custody_rule" in tool_names, \
            f"actions_taken: {tool_names}"

        rules = await RuleRepository(db).list_active(seeded_case.id)
        assert len(rules) >= 1
        assert any("BYDAY=MO,WE,FR" in r.rrule for r in rules), \
            f"rules rrule: {[r.rrule for r in rules]}"

        events = await EventRepository(db).list_in_range(
            seeded_case.id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert len(events) > 0, "custody_events 應有展開的事件"
    finally:
        await db.close()
        await engine.dispose()
