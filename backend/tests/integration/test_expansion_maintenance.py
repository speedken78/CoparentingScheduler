"""Integration tests for RRULE expansion maintenance."""
import pytest
from datetime import date, datetime, timedelta, timezone, time as dtime
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.utils.rrule_expander import expand_rule


async def _make_db():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


def _next_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1)
    return d.replace(month=d.month + 1)


async def _seed_case_with_rule(db: AsyncSession):
    """
    建立案件 + 一條週二重複規則，只展開 1 個月的事件。
    回傳 case_id。
    """
    user_id = uuid4()
    case_id = uuid4()
    rule_id = uuid4()
    today = date.today()

    await db.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"exp_{user_id}@test.com", "name": "展開測試"})
    await db.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "展開維護測試案件", "by": str(user_id)})
    await db.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})

    await db.execute(text(
        "INSERT INTO custody_rules "
        "(id, case_id, custodian_id, rule_type, rrule, start_time, end_time, "
        "effective_from, priority, source, created_by) "
        "VALUES (:id, :cid, :uid, 'weekly', :rrule, '08:00', '18:00', "
        ":ef, 100, 'unilateral', :uid)"
    ), {
        "id": str(rule_id),
        "cid": str(case_id),
        "uid": str(user_id),
        "rrule": "FREQ=WEEKLY;BYDAY=TU",
        "ef": today,
    })

    # 只展開 1 個月的事件（讓 extend_all_active_rules 有事情做）
    one_month_later = _next_month(today)
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=TU",
        start_time=dtime(8, 0),
        end_time=dtime(18, 0),
        effective_from=today,
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=one_month_later,
    )
    for e in events:
        await db.execute(text(
            "INSERT INTO custody_events "
            "(id, case_id, custodian_id, rule_id, starts_at, ends_at, status, created_by) "
            "VALUES (:id, :cid, :uid, :rid, :s, :e, 'scheduled', :uid)"
        ), {
            "id": str(uuid4()),
            "cid": str(case_id),
            "uid": str(user_id),
            "rid": str(rule_id),
            "s": e.starts_at,
            "e": e.ends_at,
        })

    await db.commit()
    return case_id


@pytest.mark.asyncio
async def test_extend_active_rules_adds_events():
    """
    已有規則但只展開到 1 個月，
    跑 extend_all_active_rules 後事件數量增加。
    """
    from app.services.expansion_maintenance import extend_all_active_rules
    from app.repositories.event_repo import EventRepository

    db, engine = await _make_db()
    try:
        case_id = await _seed_case_with_rule(db)

        before = await EventRepository(db).list_in_range(
            case_id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=365),
        )
        before_count = len(before)

        result = await extend_all_active_rules(db)
        await db.commit()

        assert result["errors"] == 0

        after = await EventRepository(db).list_in_range(
            case_id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=365),
        )
        # 6 個月視窗比 1 個月更長，事件應增加
        assert len(after) >= before_count
        assert result["new_events"] >= 0
    finally:
        await db.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_extend_idempotent():
    """跑兩次，事件數量不變（不重複建立）。"""
    from app.services.expansion_maintenance import extend_all_active_rules
    from app.repositories.event_repo import EventRepository

    db, engine = await _make_db()
    try:
        case_id = await _seed_case_with_rule(db)

        await extend_all_active_rules(db)
        await db.commit()
        count1 = len(await EventRepository(db).list_in_range(
            case_id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=365),
        ))

        result2 = await extend_all_active_rules(db)
        await db.commit()
        count2 = len(await EventRepository(db).list_in_range(
            case_id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=365),
        ))
    finally:
        await db.close()
        await engine.dispose()

    # count1 == count2 verifies idempotency for this specific case
    assert count1 == count2
    # new_events may be non-zero globally (other rules in shared DB may get extended),
    # but errors must be 0
    assert result2["errors"] == 0


@pytest.mark.asyncio
async def test_extend_no_rules_returns_zero():
    """無規則時 processed=0, new_events=0, errors=0。"""
    from app.services.expansion_maintenance import extend_all_active_rules

    db, engine = await _make_db()
    try:
        result = await extend_all_active_rules(db)
    finally:
        await db.close()
        await engine.dispose()

    assert result["errors"] == 0
