"""Integration test fixtures — requires running PostgreSQL."""
import pytest
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


async def make_superuser_session():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()
    return session, engine


@pytest.fixture
async def db():
    """Fresh superuser DB session for a single test (inserts, queries without RLS)."""
    session, engine = await make_superuser_session()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture
async def db_session():
    """Alias for db — used by schedule_service integration tests."""
    session, engine = await make_superuser_session()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture
async def seeded_case(db_session):
    """
    建立最小化測試案件（parent_a + case + membership + agent_session），
    回傳 SimpleNamespace(id, parent_a_id, agent_session_id)。
    """
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()

    await db_session.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"seeded_{user_id}@test.com", "name": "測試家長A"})

    await db_session.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "整合測試案件", "by": str(user_id)})

    await db_session.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})

    await db_session.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})

    await db_session.commit()

    return SimpleNamespace(
        id=case_id,
        parent_a_id=user_id,
        agent_session_id=session_id,
    )


@pytest.fixture
async def seeded_case_with_event(db_session):
    """
    建立案件 + 一筆已有的 custody_event，用於衝突測試。
    回傳 SimpleNamespace(id, parent_a_id, agent_session_id, event_starts_at, event_ends_at)。
    """
    user_id = uuid4()
    case_id = uuid4()
    session_id = uuid4()
    event_id = uuid4()

    await db_session.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"seeded_ev_{user_id}@test.com", "name": "測試家長EV"})

    await db_session.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "衝突測試案件", "by": str(user_id)})

    await db_session.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})

    await db_session.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(session_id), "cid": str(case_id), "uid": str(user_id)})

    event_starts_at = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    event_ends_at = datetime(2026, 6, 1, 18, 0, tzinfo=timezone.utc)
    await db_session.execute(text(
        "INSERT INTO custody_events "
        "(id, case_id, custodian_id, starts_at, ends_at, status, created_by) "
        "VALUES (:id, :cid, :uid, :s, :e, 'scheduled', :uid)"
    ), {
        "id": str(event_id), "cid": str(case_id), "uid": str(user_id),
        "s": event_starts_at, "e": event_ends_at,
    })

    await db_session.commit()

    return SimpleNamespace(
        id=case_id,
        parent_a_id=user_id,
        agent_session_id=session_id,
        event_starts_at=event_starts_at,
        event_ends_at=event_ends_at,
    )
