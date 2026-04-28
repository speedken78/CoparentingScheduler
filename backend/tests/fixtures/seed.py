"""
seed.py – 產生測試資料（依 DATABASE.md §7）

產生：
- 2 個測試家庭案件
- 每案各 2 位家長 + 1 位小孩
- 每案 1 條 weekly 規則 + 1 條 monthly_nth_weekday 規則
- 各展開 3 個月的 custody_events（簡化版：不呼叫 rrule_expander，直接插入固定事件）
- 少量 handover_records 與 audit_log（hash chain 完整）

執行方式：
    python -m tests.fixtures.seed
"""
import asyncio
import sys
import os
from datetime import date, datetime, timezone, time, timedelta
from uuid import uuid4

# 讓 Python 可以找到 app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.utils.hash_chain import compute_row_hash

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def seed(db: AsyncSession) -> None:
    # ── 使用者 ────────────────────────────────────────────────────────────────

    user_ids = [uuid4() for _ in range(4)]  # case1: u0, u1 | case2: u2, u3

    for i, uid in enumerate(user_ids):
        await db.execute(text("""
            INSERT INTO users (id, email, display_name, role)
            VALUES (:id, :email, :display_name, 'parent')
        """), {"id": str(uid), "email": f"test_user_{i}@example.com", "display_name": f"測試家長{i}"})

    # ── 案件 ──────────────────────────────────────────────────────────────────

    case_ids = [uuid4(), uuid4()]

    for i, (cid, creator) in enumerate(zip(case_ids, [user_ids[0], user_ids[2]])):
        await db.execute(text("""
            INSERT INTO family_cases (id, case_name, custody_type, created_by)
            VALUES (:id, :name, 'joint', :creator)
        """), {"id": str(cid), "name": f"測試案件{i+1}", "creator": str(creator)})

    # ── 成員關係 ──────────────────────────────────────────────────────────────

    memberships = [
        (case_ids[0], user_ids[0], "parent_a"),
        (case_ids[0], user_ids[1], "parent_b"),
        (case_ids[1], user_ids[2], "parent_a"),
        (case_ids[1], user_ids[3], "parent_b"),
    ]
    for cid, uid, relation in memberships:
        await db.execute(text("""
            INSERT INTO case_memberships (id, case_id, user_id, relation)
            VALUES (:id, :case_id, :user_id, :relation)
        """), {"id": str(uuid4()), "case_id": str(cid), "user_id": str(uid), "relation": relation})

    # ── 小孩 ──────────────────────────────────────────────────────────────────

    child_ids = [uuid4(), uuid4()]

    for i, (kid, cid) in enumerate(zip(child_ids, case_ids)):
        await db.execute(text("""
            INSERT INTO children (id, case_id, display_name, birth_date)
            VALUES (:id, :case_id, :name, :bdate)
        """), {"id": str(kid), "case_id": str(cid), "name": f"小孩{i+1}", "bdate": date(2018, 1, 1 + i)})

    # ── 監護規則 ──────────────────────────────────────────────────────────────

    rule_ids = [uuid4() for _ in range(4)]  # 每案 2 條

    rules = [
        # case 1
        (rule_ids[0], case_ids[0], child_ids[0], user_ids[0], "weekly",
         "FREQ=WEEKLY;BYDAY=MO,WE,FR", date(2026, 1, 1), "court_order"),
        (rule_ids[1], case_ids[0], child_ids[0], user_ids[1], "monthly_nth_weekday",
         "FREQ=MONTHLY;BYDAY=2SU", date(2026, 1, 1), "mutual_agreement"),
        # case 2
        (rule_ids[2], case_ids[1], child_ids[1], user_ids[2], "weekly",
         "FREQ=WEEKLY;BYDAY=TU,TH", date(2026, 1, 1), "court_order"),
        (rule_ids[3], case_ids[1], child_ids[1], user_ids[3], "monthly_nth_weekday",
         "FREQ=MONTHLY;BYDAY=1SA", date(2026, 1, 1), "mutual_agreement"),
    ]

    for rid, cid, kid, custodian, rtype, rrule, eff_from, source in rules:
        await db.execute(text("""
            INSERT INTO custody_rules
                (id, case_id, child_id, custodian_id, rule_type, rrule,
                 start_time, end_time, effective_from, source, created_by)
            VALUES
                (:id, :case_id, :child_id, :custodian_id, :rule_type, :rrule,
                 '08:00', '20:00', :effective_from, :source, :custodian_id)
        """), {
            "id": str(rid), "case_id": str(cid), "child_id": str(kid),
            "custodian_id": str(custodian), "rule_type": rtype, "rrule": rrule,
            "effective_from": eff_from, "source": source,
        })

    # ── 具體事件（每條規則展開 3 個月，簡化為每月 1 筆）────────────────────

    event_ids: list[str] = []
    base = datetime(2026, 1, 6, 8, 0, tzinfo=timezone.utc)  # 2026-01-06 週二

    for month_offset in range(3):
        start = base + timedelta(days=30 * month_offset)
        end = start + timedelta(hours=12)

        for rule_idx, (rid, cid, kid, custodian, *_) in enumerate(rules):
            eid = str(uuid4())
            event_ids.append(eid)
            await db.execute(text("""
                INSERT INTO custody_events
                    (id, case_id, child_id, custodian_id, rule_id,
                     starts_at, ends_at, status, created_by)
                VALUES
                    (:id, :case_id, :child_id, :custodian_id, :rule_id,
                     :starts_at, :ends_at, 'scheduled', :custodian_id)
            """), {
                "id": eid,
                "case_id": str(cid),
                "child_id": str(kid),
                "custodian_id": str(custodian),
                "rule_id": str(rid),
                "starts_at": start + timedelta(days=rule_idx),
                "ends_at": end + timedelta(days=rule_idx),
            })

    # ── Handover records（取前 2 筆事件各建一筆打卡）────────────────────────

    for eid in event_ids[:2]:
        await db.execute(text("""
            INSERT INTO handover_records
                (id, event_id, action, performed_by, performed_at,
                 location_lat, location_lng)
            VALUES
                (:id, :event_id, 'pickup', :performer, :performed_at, 25.033, 121.565)
        """), {
            "id": str(uuid4()),
            "event_id": eid,
            "performer": str(user_ids[0]),
            "performed_at": _now(),
        })

    # ── Audit log（hash chain 完整）─────────────────────────────────────────

    audit_entries = [
        {
            "case_id": case_ids[0],
            "actor_id": user_ids[0],
            "action": "create_custody_rule",
            "entity_type": "custody_rule",
            "entity_id": rule_ids[0],
            "before_state": None,
            "after_state": {"rule_type": "weekly", "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR"},
            "triggered_by": "human",
            "occurred_at": _now(),
        },
        {
            "case_id": case_ids[0],
            "actor_id": user_ids[0],
            "action": "create_custody_rule",
            "entity_type": "custody_rule",
            "entity_id": rule_ids[1],
            "before_state": None,
            "after_state": {"rule_type": "monthly_nth_weekday", "rrule": "FREQ=MONTHLY;BYDAY=2SU"},
            "triggered_by": "human",
            "occurred_at": _now(),
        },
    ]

    import json
    prev_hash = None
    for entry in audit_entries:
        row_hash = compute_row_hash(
            {
                "case_id": entry["case_id"],
                "actor_id": entry["actor_id"],
                "action": entry["action"],
                "entity_type": entry["entity_type"],
                "entity_id": entry["entity_id"],
                "before_state": entry["before_state"],
                "after_state": entry["after_state"],
                "triggered_by": entry["triggered_by"],
                "occurred_at": entry["occurred_at"],
            },
            prev_hash,
        )
        await db.execute(text("""
            INSERT INTO audit_log
                (case_id, actor_id, action, entity_type, entity_id,
                 before_state, after_state, triggered_by, occurred_at,
                 prev_hash, row_hash)
            VALUES
                (:case_id, :actor_id, :action, :entity_type, :entity_id,
                 :before_state, :after_state, :triggered_by, :occurred_at,
                 :prev_hash, :row_hash)
        """), {
            "case_id": str(entry["case_id"]),
            "actor_id": str(entry["actor_id"]),
            "action": entry["action"],
            "entity_type": entry["entity_type"],
            "entity_id": str(entry["entity_id"]),
            "before_state": json.dumps(entry["before_state"]) if entry["before_state"] else None,
            "after_state": json.dumps(entry["after_state"]) if entry["after_state"] else None,
            "triggered_by": entry["triggered_by"],
            "occurred_at": entry["occurred_at"],
            "prev_hash": prev_hash,
            "row_hash": row_hash,
        })
        prev_hash = row_hash

    await db.commit()
    print("✅ Seed 完成")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
