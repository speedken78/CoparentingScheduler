# MILESTONE_1_4.md｜RRULE 展開與真實寫入

> 本 Milestone 把 M1.3 的 schedule_service stub 換成真實實作。
> 閱讀順序：本文件 → DATABASE.md（custody_rules / custody_events / audit_log）→ M1.3 的 schedule_service.py
> 完成後跑 §9 DoD，全部通過才算完成。

---

## 0. 本 Milestone 的交付範圍

| 交付項目 | 說明 |
|---|---|
| `app/utils/rrule_expander.py` | iCal RRULE 展開成 custody_events |
| `app/repositories/rule_repo.py` | CustodyRule CRUD |
| `app/repositories/event_repo.py` | CustodyEvent CRUD（bulk insert） |
| `app/repositories/revocation_proposal_repo.py` | 撤銷提案 |
| `app/services/schedule_service.py` | 替換 stub 為真實實作 |
| `app/api/v1/schedules.py` | 排程相關 REST endpoints |
| Migration 011 | 新增 `revocation_proposals` 表 |
| `tests/unit/test_rrule_expander.py` | 展開邏輯測試 |
| `tests/integration/test_schedule_service.py` | 整合測試 |
| `tests/agent_evals/test_scheduler_evals.py` 更新 | B/C 系列測真實寫入 |

---

## 1. 展開策略與時間線概念

### 1.1 展開視窗

- 規則建立時，**展開未來 6 個月的事件**到 `custody_events`
- 每日 cron job 往後補展開，維持「永遠有未來 6 個月的事件」
- 規則撤銷時，**只刪除 `revoked_at` 之後的 scheduled 事件**（已發生、已確認、已爭議的不動）

### 1.2 規則變更的語意

不允許「原地修改規則」。所有變更都是「撤銷舊規則 + 建立新規則」，保留完整歷史：

```
舊規則：週一三五 speaker 帶（2026-01-01 起）
使用者改成「週一二三 speaker 帶」
  ↓
撤銷舊規則（revoked_at=2026-04-23，revoked_reason="改為週一二三"）
刪除 2026-04-23 之後由舊規則展開的 scheduled 事件
建立新規則（effective_from=2026-04-23）
展開新規則的事件
```

這個設計讓稽核軌跡完整，法院調閱時能清楚看到「何時改變了什麼」。

### 1.3 已發生事件的保護

已發生（status 為 `completed` / `missed` / `disputed`）或手動修改（`rule_id` 為 null 的單一事件）的 `custody_events` **永遠不動**。只有 `status='scheduled'` 且 `rule_id` 對應被撤銷規則的事件才會被清除。

---

## 2. Migration 011：revocation_proposals

`alembic/versions/011_revocation_proposals.py`：

```python
"""011: revocation proposals

Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.execute("""
        CREATE TABLE revocation_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id UUID NOT NULL REFERENCES family_cases(id),
            rule_id UUID REFERENCES custody_rules(id),
            rule_hint TEXT NOT NULL,
            revocation_reason TEXT NOT NULL,
            effective_from DATE NOT NULL,
            proposed_by UUID NOT NULL REFERENCES users(id),
            agent_session_id UUID REFERENCES agent_sessions(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','confirmed','rejected','expired')),
            confirmed_at TIMESTAMPTZ,
            confirmed_by UUID REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')
        );

        CREATE INDEX idx_revocation_case_status
            ON revocation_proposals(case_id, status);
    """)

    # RLS
    op.execute("""
        ALTER TABLE revocation_proposals ENABLE ROW LEVEL SECURITY;
        ALTER TABLE revocation_proposals FORCE ROW LEVEL SECURITY;

        CREATE POLICY revocation_proposals_case_isolation
            ON revocation_proposals
            FOR ALL
            USING (case_id = ANY(get_user_case_ids()));

        GRANT SELECT, INSERT, UPDATE, DELETE ON revocation_proposals TO app_role;
    """)

def downgrade():
    op.execute("DROP TABLE IF EXISTS revocation_proposals CASCADE;")
```

---

## 3. RRULE Expander（`app/utils/rrule_expander.py`）

### 3.1 介面

```python
from datetime import datetime, date, time, timedelta
from uuid import UUID
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr


@dataclass
class ExpandedEvent:
    """展開後的單一事件（尚未落庫）。"""
    starts_at: datetime  # aware datetime
    ends_at: datetime    # aware datetime


def expand_rule(
    rrule_str: str,
    start_time: time,
    end_time: time,
    effective_from: date,
    effective_until: date | None,
    timezone: str,
    expand_until: date,
) -> list[ExpandedEvent]:
    """
    將規則展開成具體事件清單。

    Args:
        rrule_str: iCal RRULE 字串（不含 DTSTART），例如 "FREQ=WEEKLY;BYDAY=MO,WE,FR"
        start_time: 每日起始時間（該時區）
        end_time: 每日結束時間（該時區）
        effective_from: 規則生效起始日（含）
        effective_until: 規則結束日（含），None 表示無限期
        timezone: IANA 時區名稱，例如 "Asia/Taipei"
        expand_until: 展開到此日期為止（含）

    Returns:
        list[ExpandedEvent]，按 starts_at 升序

    Raises:
        ValueError: rrule_str 無效
    """
    tz = ZoneInfo(timezone)

    # dtstart 設為 effective_from 的 start_time
    dtstart = datetime.combine(effective_from, start_time, tzinfo=tz)

    # 有效截止日 = min(effective_until, expand_until)
    hard_until_date = min(effective_until, expand_until) if effective_until else expand_until
    # until 用當日的 end_time 作為 inclusive 上限
    until_dt = datetime.combine(hard_until_date, time(23, 59, 59), tzinfo=tz)

    try:
        rule = rrulestr(rrule_str, dtstart=dtstart)
    except Exception as e:
        raise ValueError(f"Invalid RRULE: {rrule_str}") from e

    events: list[ExpandedEvent] = []
    for occurrence in rule:
        if occurrence > until_dt:
            break
        # 把 occurrence 的日期套用 start_time / end_time
        day = occurrence.date()
        starts_at = datetime.combine(day, start_time, tzinfo=tz)
        ends_at = datetime.combine(day, end_time, tzinfo=tz)

        # 跨日處理：若 end_time <= start_time，視為跨日事件（隔天）
        if ends_at <= starts_at:
            ends_at = ends_at + timedelta(days=1)

        events.append(ExpandedEvent(starts_at=starts_at, ends_at=ends_at))

    return events
```

### 3.2 必須支援的 RRULE 模式

| 模式 | RRULE 範例 |
|---|---|
| 每週一三五 | `FREQ=WEEKLY;BYDAY=MO,WE,FR` |
| 隔週週末 | `FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU` |
| 每月第二個週日 | `FREQ=MONTHLY;BYDAY=2SU` |
| 每月第 1、3、5 週的週日 | `FREQ=MONTHLY;BYDAY=1SU,3SU,5SU` |
| 含結束日 | `FREQ=WEEKLY;BYDAY=MO;UNTIL=20261231T235959Z` |
| 含次數上限 | `FREQ=WEEKLY;BYDAY=MO;COUNT=10` |

### 3.3 Unit test（`tests/unit/test_rrule_expander.py`）

```python
import pytest
from datetime import date, time
from app.utils.rrule_expander import expand_rule


def test_weekly_mwf():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=MO,WE,FR",
        start_time=time(7, 30),
        end_time=time(17, 30),
        effective_from=date(2026, 1, 5),  # 週一
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 18),   # 展開兩週
    )
    # 兩週 × 3 天 = 6 個事件
    assert len(events) == 6
    assert events[0].starts_at.hour == 7 and events[0].starts_at.minute == 30
    assert events[0].ends_at.hour == 17 and events[0].ends_at.minute == 30
    # 第一個應為 1/5（週一）
    assert events[0].starts_at.date() == date(2026, 1, 5)
    # 最後一個應為 1/16（週五）
    assert events[-1].starts_at.date() == date(2026, 1, 16)


def test_biweekly_weekend():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU",
        start_time=time(9, 0),
        end_time=time(18, 0),
        effective_from=date(2026, 1, 3),  # 週六
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 31),
    )
    # 1/3-4（第1週週末）+ 1/17-18（第3週）+ 1/31（第5週週六）
    assert len(events) >= 4


def test_monthly_second_sunday():
    events = expand_rule(
        rrule_str="FREQ=MONTHLY;BYDAY=2SU",
        start_time=time(9, 0),
        end_time=time(18, 0),
        effective_from=date(2026, 1, 1),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 6, 30),
    )
    # 每月一次 × 6 個月
    assert len(events) == 6


def test_with_until():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=MO;UNTIL=20260131T235959Z",
        start_time=time(7, 30),
        end_time=time(17, 30),
        effective_from=date(2026, 1, 5),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 12, 31),
    )
    # 1月的週一：1/5, 1/12, 1/19, 1/26 = 4 個
    assert len(events) == 4


def test_with_count():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=MO;COUNT=5",
        start_time=time(7, 30),
        end_time=time(17, 30),
        effective_from=date(2026, 1, 5),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 12, 31),
    )
    assert len(events) == 5


def test_invalid_rrule():
    with pytest.raises(ValueError):
        expand_rule(
            rrule_str="INVALID_RRULE",
            start_time=time(9, 0),
            end_time=time(18, 0),
            effective_from=date(2026, 1, 1),
            effective_until=None,
            timezone="Asia/Taipei",
            expand_until=date(2026, 1, 31),
        )


def test_effective_until_respected():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=MO",
        start_time=time(7, 30),
        end_time=time(17, 30),
        effective_from=date(2026, 1, 5),
        effective_until=date(2026, 2, 28),  # 2 月底結束
        timezone="Asia/Taipei",
        expand_until=date(2026, 12, 31),
    )
    # 1月+2月的週一
    assert all(e.starts_at.date() <= date(2026, 2, 28) for e in events)


def test_overnight_event():
    """跨日事件：end_time 小於 start_time 表示隔天結束。"""
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=FR",
        start_time=time(20, 0),
        end_time=time(8, 0),   # 小於 start_time → 隔天早上
        effective_from=date(2026, 1, 2),  # 週五
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 9),
    )
    assert len(events) == 1
    # ends_at 應是隔天
    assert events[0].ends_at.date() == date(2026, 1, 3)
```

---

## 4. Repositories

### 4.1 `app/repositories/rule_repo.py`

```python
from uuid import UUID
from datetime import date, time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.models.custody_rule import CustodyRule


class RuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> CustodyRule:
        rule = CustodyRule(**data)
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def get_by_id(self, rule_id: UUID) -> CustodyRule | None:
        return await self.db.get(CustodyRule, rule_id)

    async def list_active(self, case_id: UUID) -> list[CustodyRule]:
        result = await self.db.execute(
            select(CustodyRule)
            .where(
                and_(
                    CustodyRule.case_id == case_id,
                    CustodyRule.revoked_at.is_(None),
                )
            )
            .order_by(CustodyRule.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke(
        self,
        rule_id: UUID,
        revoked_by: UUID,
        revoked_reason: str,
        revoked_at_date,
    ) -> CustodyRule | None:
        """標記撤銷。不實際刪除。"""
        from datetime import datetime, timezone
        rule = await self.get_by_id(rule_id)
        if not rule or rule.revoked_at is not None:
            return None
        rule.revoked_at = datetime.now(timezone.utc)
        rule.revoked_by = revoked_by
        rule.revoked_reason = revoked_reason
        await self.db.flush()
        return rule
```

### 4.2 `app/repositories/event_repo.py`

```python
from uuid import UUID
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, delete
from app.models.custody_event import CustodyEvent


class EventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def bulk_insert(self, events_data: list[dict]) -> list[CustodyEvent]:
        """一次插入多個事件。若 exclusion constraint 擋下，回傳已成功的部分。"""
        events = [CustodyEvent(**d) for d in events_data]
        self.db.add_all(events)
        await self.db.flush()
        return events

    async def list_in_range(
        self,
        case_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[CustodyEvent]:
        result = await self.db.execute(
            select(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.case_id == case_id,
                    CustodyEvent.deleted_at.is_(None),
                    CustodyEvent.starts_at < end,
                    CustodyEvent.ends_at > start,
                )
            )
            .order_by(CustodyEvent.starts_at.asc())
        )
        return list(result.scalars().all())

    async def delete_scheduled_by_rule_after(
        self,
        rule_id: UUID,
        after: datetime,
    ) -> int:
        """
        軟刪除某規則展開的、在指定時間之後、狀態為 scheduled 的事件。
        回傳刪除筆數。
        """
        from datetime import timezone as dt_tz
        result = await self.db.execute(
            update(CustodyEvent)
            .where(
                and_(
                    CustodyEvent.rule_id == rule_id,
                    CustodyEvent.starts_at >= after,
                    CustodyEvent.status == "scheduled",
                    CustodyEvent.deleted_at.is_(None),
                )
            )
            .values(deleted_at=datetime.now(dt_tz.utc))
            .execution_options(synchronize_session=False)
        )
        return result.rowcount
```

### 4.3 `app/repositories/revocation_proposal_repo.py`

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.revocation_proposal import RevocationProposal


class RevocationProposalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> RevocationProposal:
        p = RevocationProposal(**data)
        self.db.add(p)
        await self.db.flush()
        return p

    async def get_by_id(self, proposal_id: UUID) -> RevocationProposal | None:
        return await self.db.get(RevocationProposal, proposal_id)

    async def list_pending(self, case_id: UUID) -> list[RevocationProposal]:
        result = await self.db.execute(
            select(RevocationProposal)
            .where(
                RevocationProposal.case_id == case_id,
                RevocationProposal.status == "pending",
            )
            .order_by(RevocationProposal.created_at.desc())
        )
        return list(result.scalars().all())
```

**注意**：對應的 `app/models/revocation_proposal.py` 也要建立 ORM 類別，欄位與 Migration 011 一致。

---

## 5. Schedule Service（真實實作）

替換 M1.3 的 stub。`detect_conflicts` 保留不動（M1.3 已實作）。

### 5.1 `create_rule`

```python
# app/services/schedule_service.py（補充 / 替換）
from datetime import datetime, timedelta, time as dtime, date as ddate, timezone as dt_tz
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import AgentContext
from app.models.case_membership import CaseMembership
from app.repositories.rule_repo import RuleRepository
from app.repositories.event_repo import EventRepository
from app.repositories.revocation_proposal_repo import RevocationProposalRepository
from app.services.audit_service import log as audit_log
from app.utils.rrule_expander import expand_rule
from sqlalchemy import select, and_


EXPAND_WINDOW_MONTHS = 6


async def _resolve_custodian_user_id(
    ctx: AgentContext,
    custodian_label: str,
    db: AsyncSession,
) -> UUID:
    """
    把 LLM 的 "speaker" / "counterparty" 轉成實際 user_id。
    speaker = ctx.speaker_user_id
    counterparty = case 內另一位 parent（parent_a / parent_b）
    """
    if custodian_label == "speaker":
        return ctx.speaker_user_id

    # 找另一位 parent
    result = await db.execute(
        select(CaseMembership)
        .where(
            and_(
                CaseMembership.case_id == ctx.case_id,
                CaseMembership.user_id != ctx.speaker_user_id,
                CaseMembership.relation.in_(["parent_a", "parent_b"]),
                CaseMembership.revoked_at.is_(None),
            )
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        # 單方使用場景：對方還沒加入，用 speaker 自己的 id 作為 placeholder
        # 未來對方加入時，有專門流程處理 user_id 替換（M2.1）
        # 這裡的折衷是在 notes 標註 custodian 是 counterparty
        return ctx.speaker_user_id
    return member.user_id


async def create_rule(ctx: AgentContext, tool_input: dict, db: AsyncSession) -> dict:
    """
    真實實作：建立規則 + 展開未來 6 個月事件 + 寫 audit_log。
    所有寫入在當前 transaction 內（由 agent_service 的 begin_nested 管理）。
    """
    rule_repo = RuleRepository(db)
    event_repo = EventRepository(db)

    # 1. 解析 custodian
    custodian_id = await _resolve_custodian_user_id(
        ctx, tool_input["custodian"], db
    )
    is_counterparty = (tool_input["custodian"] == "counterparty")

    # 2. 解析時間字串
    start_time = dtime.fromisoformat(tool_input["start_time"])
    end_time = dtime.fromisoformat(tool_input["end_time"])
    effective_from = ddate.fromisoformat(tool_input["effective_from"])
    effective_until = (
        ddate.fromisoformat(tool_input["effective_until"])
        if tool_input.get("effective_until") else None
    )

    # 3. 決定 rule_type
    rrule_str = tool_input["rrule"]
    rule_type = _infer_rule_type(rrule_str)

    # 4. 建立 rule
    rule_data = {
        "case_id": ctx.case_id,
        "child_id": None,   # M1.4 不處理 specific_child，M2 再加
        "custodian_id": custodian_id,
        "rule_type": rule_type,
        "rrule": rrule_str,
        "start_time": start_time,
        "end_time": end_time,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "priority": 100,
        "source": tool_input.get("source", "unilateral"),
        "notes": (
            f"[counterparty placeholder] {tool_input.get('reasoning', '')}"
            if is_counterparty and custodian_id == ctx.speaker_user_id
            else tool_input.get("reasoning", "")
        ),
        "created_by": ctx.speaker_user_id,
    }
    rule = await rule_repo.insert(rule_data)

    # 5. 展開 6 個月事件
    expand_until = _add_months(ddate.today(), EXPAND_WINDOW_MONTHS)
    expanded = expand_rule(
        rrule_str=rrule_str,
        start_time=start_time,
        end_time=end_time,
        effective_from=effective_from,
        effective_until=effective_until,
        timezone=ctx.case_timezone,
        expand_until=expand_until,
    )

    events_data = [
        {
            "case_id": ctx.case_id,
            "child_id": None,
            "custodian_id": custodian_id,
            "rule_id": rule.id,
            "starts_at": e.starts_at,
            "ends_at": e.ends_at,
            "status": "scheduled",
            "created_by": ctx.speaker_user_id,
        }
        for e in expanded
    ]

    # 6. Bulk insert events（可能被 exclusion constraint 擋下）
    inserted_events = []
    skipped_count = 0
    for event_data in events_data:
        try:
            async with db.begin_nested():   # 每個事件獨立 savepoint
                e = await event_repo.bulk_insert([event_data])
                inserted_events.extend(e)
        except Exception:
            # 被 constraint 擋下（時段衝突），跳過該事件
            skipped_count += 1

    # 7. 寫 audit_log
    await audit_log(
        db,
        case_id=ctx.case_id,
        actor_id=ctx.speaker_user_id,
        action="create_custody_rule",
        entity_type="custody_rule",
        entity_id=rule.id,
        before_state=None,
        after_state={
            "rrule": rrule_str,
            "custodian": tool_input["custodian"],
            "start_time": str(start_time),
            "end_time": str(end_time),
            "effective_from": str(effective_from),
            "effective_until": str(effective_until) if effective_until else None,
            "source": rule_data["source"],
            "expanded_events_count": len(inserted_events),
            "skipped_events_count": skipped_count,
        },
        triggered_by="agent",
        agent_session_id=ctx.session_id,
    )

    return {
        "id": rule.id,
        "summary": (
            f"已建立規則：{_summarize_rrule(rrule_str)} "
            f"{start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}，"
            f"展開 {len(inserted_events)} 個事件"
            + (f"，{skipped_count} 個因衝突跳過" if skipped_count else "")
        ),
        "expanded_events_count": len(inserted_events),
        "skipped_events_count": skipped_count,
    }


def _infer_rule_type(rrule: str) -> str:
    parts = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    freq = parts.get("FREQ", "")
    interval = parts.get("INTERVAL", "1")
    byday = parts.get("BYDAY", "")

    if freq == "WEEKLY" and interval == "2":
        return "biweekly"
    if freq == "WEEKLY":
        return "weekly"
    if freq == "MONTHLY" and any(c.isdigit() for c in byday):
        return "monthly_nth_weekday"
    return "custom_rrule"


def _summarize_rrule(rrule: str) -> str:
    """簡短的人類可讀摘要，給 audit 與 UI 用。不需完美。"""
    # 沿用 M1.3 context.py 的 _rrule_to_human 邏輯，或呼叫它
    from app.agents.context import _rrule_to_human
    return _rrule_to_human(rrule)


def _add_months(d: ddate, months: int) -> ddate:
    import calendar
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return ddate(year, month, day)
```

### 5.2 `create_event`

```python
async def create_event(ctx: AgentContext, tool_input: dict, db: AsyncSession) -> dict:
    event_repo = EventRepository(db)

    custodian_id = await _resolve_custodian_user_id(
        ctx, tool_input["custodian"], db
    )

    starts_at = datetime.fromisoformat(tool_input["starts_at"])
    ends_at = datetime.fromisoformat(tool_input["ends_at"])

    event_data = {
        "case_id": ctx.case_id,
        "child_id": None,
        "custodian_id": custodian_id,
        "rule_id": None,                    # 單一事件沒有 rule
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "scheduled",
        "handover_location": tool_input.get("handover_location"),
        "notes": tool_input.get("notes") or tool_input.get("reasoning", ""),
        "created_by": ctx.speaker_user_id,
    }

    try:
        events = await event_repo.bulk_insert([event_data])
        event = events[0]
    except Exception as e:
        return {
            "status": "conflict_blocked",
            "message": "此時段與現有事件重疊，無法建立",
        }

    await audit_log(
        db,
        case_id=ctx.case_id,
        actor_id=ctx.speaker_user_id,
        action="create_custody_event",
        entity_type="custody_event",
        entity_id=event.id,
        before_state=None,
        after_state={
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "custodian": tool_input["custodian"],
            "notes": event_data["notes"],
        },
        triggered_by="agent",
        agent_session_id=ctx.session_id,
    )

    return {
        "id": event.id,
        "summary": (
            f"已建立事件：{starts_at.strftime('%Y-%m-%d %H:%M')} – "
            f"{ends_at.strftime('%H:%M')}"
        ),
    }
```

### 5.3 `propose_revocation`

```python
async def propose_revocation(
    ctx: AgentContext, tool_input: dict, db: AsyncSession
) -> dict:
    """
    建立撤銷提案（狀態 pending），不實際撤銷。
    使用者在 UI 確認後才呼叫 confirm_revocation。
    """
    proposal_repo = RevocationProposalRepository(db)

    # 嘗試比對 rule_hint 到現有規則（best-effort）
    rule_id = await _find_rule_by_hint(ctx, tool_input["rule_hint"], db)

    proposal = await proposal_repo.insert({
        "case_id": ctx.case_id,
        "rule_id": rule_id,    # 可能為 None（比對不到）
        "rule_hint": tool_input["rule_hint"],
        "revocation_reason": tool_input["revocation_reason"],
        "effective_from": ddate.fromisoformat(tool_input["effective_from"]),
        "proposed_by": ctx.speaker_user_id,
        "agent_session_id": ctx.session_id,
    })

    await audit_log(
        db,
        case_id=ctx.case_id,
        actor_id=ctx.speaker_user_id,
        action="propose_revocation",
        entity_type="revocation_proposal",
        entity_id=proposal.id,
        before_state=None,
        after_state={
            "rule_id": str(rule_id) if rule_id else None,
            "rule_hint": tool_input["rule_hint"],
            "reason": tool_input["revocation_reason"],
            "effective_from": tool_input["effective_from"],
        },
        triggered_by="agent",
        agent_session_id=ctx.session_id,
    )

    return {
        "id": proposal.id,
        "rule_matched": rule_id is not None,
        "rule_id": str(rule_id) if rule_id else None,
    }


async def _find_rule_by_hint(
    ctx: AgentContext, hint: str, db: AsyncSession
) -> UUID | None:
    """
    啟發式比對：在 hint 中找週幾 / 時段的關鍵字，與現有規則比對。
    比對不到回傳 None，讓使用者在 UI 手動挑選。
    """
    rules = await RuleRepository(db).list_active(ctx.case_id)
    if not rules:
        return None

    # 超簡單的規則：若 hint 含「週 X」且某規則 RRULE 含對應 BYDAY，就匹配
    weekday_map = {
        "一": "MO", "二": "TU", "三": "WE",
        "四": "TH", "五": "FR", "六": "SA", "日": "SU",
    }
    mentioned_days = [
        code for zh, code in weekday_map.items() if f"週{zh}" in hint or f"星期{zh}" in hint
    ]
    if not mentioned_days:
        return None

    for rule in rules:
        if all(d in rule.rrule for d in mentioned_days):
            return rule.id
    return None
```

### 5.4 `confirm_revocation`（使用者確認後呼叫）

```python
async def confirm_revocation(
    proposal_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> dict:
    """
    使用者在 UI 確認撤銷後呼叫。
    - 將規則標記 revoked
    - 刪除 effective_from 之後的 scheduled 事件
    - 寫 audit_log
    """
    proposal_repo = RevocationProposalRepository(db)
    rule_repo = RuleRepository(db)
    event_repo = EventRepository(db)

    proposal = await proposal_repo.get_by_id(proposal_id)
    if not proposal or proposal.status != "pending":
        raise ValueError("Proposal not found or not pending")

    if not proposal.rule_id:
        raise ValueError("Proposal has no matched rule; cannot confirm automatically")

    # 1. 撤銷 rule
    rule = await rule_repo.revoke(
        rule_id=proposal.rule_id,
        revoked_by=user_id,
        revoked_reason=proposal.revocation_reason,
        revoked_at_date=proposal.effective_from,
    )
    if not rule:
        raise ValueError("Rule already revoked or not found")

    # 2. 刪除 effective_from 之後的 scheduled 事件
    tz = ZoneInfo("Asia/Taipei")  # 可從 case 取
    cutoff = datetime.combine(proposal.effective_from, dtime(0, 0), tzinfo=tz)
    deleted_count = await event_repo.delete_scheduled_by_rule_after(
        rule_id=proposal.rule_id,
        after=cutoff,
    )

    # 3. 更新 proposal 狀態
    proposal.status = "confirmed"
    proposal.confirmed_at = datetime.now(dt_tz.utc)
    proposal.confirmed_by = user_id
    await db.flush()

    # 4. audit_log
    await audit_log(
        db,
        case_id=proposal.case_id,
        actor_id=user_id,
        action="revoke_custody_rule",
        entity_type="custody_rule",
        entity_id=proposal.rule_id,
        before_state={"revoked": False},
        after_state={
            "revoked": True,
            "reason": proposal.revocation_reason,
            "effective_from": str(proposal.effective_from),
            "deleted_events_count": deleted_count,
        },
        triggered_by="human",
    )

    return {
        "status": "confirmed",
        "rule_id": str(proposal.rule_id),
        "deleted_events_count": deleted_count,
    }
```

---

## 6. REST Endpoints（`app/api/v1/schedules.py`）

```python
# app/api/v1/schedules.py
from uuid import UUID
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.rule_repo import RuleRepository
from app.repositories.event_repo import EventRepository
from app.repositories.revocation_proposal_repo import RevocationProposalRepository
from app.repositories.membership_repo import MembershipRepository
from app.services.schedule_service import confirm_revocation

router = APIRouter(prefix="/cases/{case_id}", tags=["schedules"])


async def _require_member(case_id: UUID, user_id: UUID, db: AsyncSession):
    m = await MembershipRepository(db).get(case_id, user_id)
    if not m:
        raise HTTPException(403, detail="您不是此案件的成員")
    return m


@router.get("/rules")
async def list_rules(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    rules = await RuleRepository(db).list_active(case_id)
    return {
        "items": [
            {
                "id": str(r.id),
                "rrule": r.rrule,
                "custodian_id": str(r.custodian_id),
                "start_time": str(r.start_time)[:5],
                "end_time": str(r.end_time)[:5],
                "effective_from": str(r.effective_from),
                "effective_until": str(r.effective_until) if r.effective_until else None,
                "source": r.source,
            }
            for r in rules
        ]
    }


@router.get("/events")
async def list_events(
    case_id: UUID,
    start: datetime = Query(...),
    end: datetime = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    events = await EventRepository(db).list_in_range(case_id, start, end)
    return {
        "items": [
            {
                "id": str(e.id),
                "starts_at": e.starts_at.isoformat(),
                "ends_at": e.ends_at.isoformat(),
                "custodian_id": str(e.custodian_id),
                "status": e.status,
                "rule_id": str(e.rule_id) if e.rule_id else None,
                "handover_location": e.handover_location,
                "notes": e.notes,
            }
            for e in events
        ]
    }


@router.get("/revocation-proposals")
async def list_revocation_proposals(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    proposals = await RevocationProposalRepository(db).list_pending(case_id)
    return {
        "items": [
            {
                "id": str(p.id),
                "rule_id": str(p.rule_id) if p.rule_id else None,
                "rule_hint": p.rule_hint,
                "revocation_reason": p.revocation_reason,
                "effective_from": str(p.effective_from),
                "expires_at": p.expires_at.isoformat(),
            }
            for p in proposals
        ]
    }


class ConfirmRevocationRequest(BaseModel):
    rule_id: UUID | None = None  # 若 proposal 未自動比對，由前端帶


@router.post("/revocation-proposals/{proposal_id}/confirm")
async def confirm_revocation_endpoint(
    case_id: UUID,
    proposal_id: UUID,
    body: ConfirmRevocationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    m = await _require_member(case_id, current_user.id, db)
    if m.relation not in ("parent_a", "parent_b"):
        raise HTTPException(403, detail="只有父母可以確認撤銷")

    # 若前端帶了 rule_id，覆蓋 proposal.rule_id
    if body.rule_id:
        proposal = await RevocationProposalRepository(db).get_by_id(proposal_id)
        if proposal:
            proposal.rule_id = body.rule_id
            await db.flush()

    try:
        async with db.begin_nested():
            result = await confirm_revocation(proposal_id, current_user.id, db)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    return result
```

**記得**在 `app/main.py` 註冊此 router：

```python
from app.api.v1 import schedules
app.include_router(schedules.router, prefix="/api/v1")
```

---

## 7. 每日展開 Cron（M1.4 只預留介面，實際排程 M1.7 處理）

建立 `app/services/expansion_maintenance.py`，暫時只提供函數，不接排程：

```python
async def extend_all_active_rules(db: AsyncSession) -> dict:
    """
    遍歷所有未撤銷規則，把展開視窗推進到 today + 6 個月。
    M1.7 會用 Cloud Scheduler 每日呼叫此函數。
    """
    # 實作摘要：
    # 1. SELECT rule FROM custody_rules WHERE revoked_at IS NULL
    # 2. 對每條規則：
    #    a. 找 rule_id 對應的最後一個 scheduled event 的 starts_at
    #    b. expand_rule(effective_from=last_event_date+1, expand_until=today+6m)
    #    c. bulk_insert 新增的事件
    # 3. 回傳每條規則新增的事件數量
    # （完整實作留到 M1.7，但本 Milestone 至少要有函數骨架與單元測試）
    pass
```

---

## 8. Integration tests（`tests/integration/test_schedule_service.py`）

```python
import pytest
from datetime import date, time
from uuid import UUID

from app.services.schedule_service import create_rule, create_event, confirm_revocation
from app.agents.context import AgentContext


@pytest.mark.asyncio
async def test_create_rule_expands_events(seeded_case, db_session):
    """建立規則後，custody_events 有對應展開。"""
    ctx = AgentContext(
        session_id=seeded_case.agent_session_id,
        case_id=seeded_case.id,
        speaker_user_id=seeded_case.parent_a_id,
        case_timezone="Asia/Taipei",
        active_rules=[],
        messages=[],
    )
    tool_input = {
        "custodian": "speaker",
        "child_scope": "all_children",
        "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
        "start_time": "07:30",
        "end_time": "17:30",
        "effective_from": date.today().isoformat(),
        "source": "unilateral",
        "confidence": 0.95,
        "reasoning": "test",
    }

    result = await create_rule(ctx, tool_input, db_session)
    assert result["expanded_events_count"] > 0

    # 查 custody_events 確認有資料
    from app.repositories.event_repo import EventRepository
    from datetime import datetime, timezone, timedelta
    events = await EventRepository(db_session).list_in_range(
        seeded_case.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=180),
    )
    assert len(events) == result["expanded_events_count"]

    # audit_log 有對應紀錄
    from app.models.audit_log import AuditLog
    from sqlalchemy import select
    r = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "create_custody_rule",
            AuditLog.entity_id == result["id"],
        )
    )
    logs = list(r.scalars().all())
    assert len(logs) == 1
    assert logs[0].triggered_by == "agent"


@pytest.mark.asyncio
async def test_one_time_event_conflict_blocked(seeded_case_with_event, db_session):
    """在已有事件的時段建立單一事件，應被擋下。"""
    ctx = AgentContext(...)
    tool_input = {
        "custodian": "speaker",
        "child_scope": "all_children",
        "starts_at": seeded_case_with_event.event_starts_at.isoformat(),
        "ends_at": seeded_case_with_event.event_ends_at.isoformat(),
        "confidence": 0.95,
        "reasoning": "test overlap",
    }
    result = await create_event(ctx, tool_input, db_session)
    assert result["status"] == "conflict_blocked"


@pytest.mark.asyncio
async def test_revocation_deletes_future_scheduled_only(seeded_case_with_rule, db_session):
    """
    撤銷規則後：
    - effective_from 之後的 scheduled 事件被軟刪除
    - effective_from 之前的事件 + 已 completed/missed 的事件保留
    """
    # 設定：建規則 + 展開事件 + 手動把其中一筆改成 completed
    # 撤銷 → 驗證
    pass  # 實作時填入完整流程
```

**`conftest.py` 的 fixture** 要新增 `seeded_case_with_rule` / `seeded_case_with_event`，或在既有 `seed.py` 擴充。

---

## 9. Agent Evals 更新

把 M1.3 的 B1/B3/B4 從「驗 tool call 格式」升級為「驗 DB 真的寫入」。
新增 `tests/agent_evals/test_scheduler_writes.py`：

```python
@pytest.mark.asyncio
@pytest.mark.eval
async def test_B1_writes_to_db(anthropic_client, seeded_case, db_session):
    """B1 升級：驗證 LLM 解析後，custody_rules 真的有資料。"""
    from app.services.agent_service import handle_message

    result = await handle_message(
        case_id=seeded_case.id,
        user_id=seeded_case.parent_a_id,
        user_text="我每週一、三、五 07:30 到 17:30 帶小孩",
        session_id=None,
        db=db_session,
    )

    # 檢查 actions_taken 包含 create_recurring_custody_rule
    tool_names = [a["tool"] for a in result["actions_taken"]]
    assert "create_recurring_custody_rule" in tool_names

    # 檢查 DB
    from app.repositories.rule_repo import RuleRepository
    rules = await RuleRepository(db_session).list_active(seeded_case.id)
    assert len(rules) >= 1
    assert any("BYDAY=MO,WE,FR" in r.rrule for r in rules)

    # 檢查展開的事件數量 > 0
    from datetime import datetime, timezone, timedelta
    from app.repositories.event_repo import EventRepository
    events = await EventRepository(db_session).list_in_range(
        seeded_case.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=180),
    )
    assert len(events) > 0
```

---

## 10. DoD（完成標準）

```bash
# Migration
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api alembic upgrade head"

# Unit tests
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/unit -v"

# Integration tests
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/integration -v"

# Agent evals（含新增的寫入驗證）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/agent_evals -v -m eval"
```

**驗證項目**：

**RRULE Expander**
- [ ] `test_rrule_expander.py` 的 8 個 case 全綠
- [ ] 特別確認跨日事件與 UNTIL / COUNT 的處理

**Repositories**
- [ ] `bulk_insert` 遇到 exclusion constraint 錯誤時，單筆 savepoint 不影響整批
- [ ] `delete_scheduled_by_rule_after` 只影響 `status='scheduled'` 的事件

**Schedule Service**
- [ ] `create_rule` 寫入 `custody_rules`、展開 `custody_events`、寫 `audit_log`（三者在同一 transaction）
- [ ] `create_event` 遇到時段衝突回傳 `conflict_blocked`，不寫入
- [ ] `propose_revocation` 寫入 `revocation_proposals`，`rule_id` 可能為 null（比對不到時）
- [ ] `confirm_revocation` 撤銷規則 + 刪除 effective_from 之後的 scheduled 事件 + 保留 completed/missed 事件

**API Endpoints**
- [ ] `GET /cases/{id}/rules`、`/events`、`/revocation-proposals` 全部 200
- [ ] `POST /revocation-proposals/{id}/confirm` 正確執行並回傳刪除事件數量
- [ ] 非成員存取一律 403

**Agent Evals**
- [ ] M1.3 所有 14 個 eval 仍全綠（包括 D 系列的安全護欄）
- [ ] 新增的寫入驗證測試：B1 寫入後 `custody_rules` 和 `custody_events` 有資料

**稽核完整性**
- [ ] 建立規則 → 撤銷規則 → 查 `audit_log`，可看到完整的 create → propose_revocation → revoke_custody_rule 軌跡
- [ ] `row_hash` 鏈在整個流程中一致

---

## 11. 給 Claude Code 的注意事項

1. **保留 M1.3 的 `detect_conflicts`**：M1.3 實作的 detect_conflicts 不需改，只是 stub 的 create_* 要替換成真實實作。

2. **`begin_nested()` 的使用**：`schedule_service` 本身不開 transaction。由 `agent_service.handle_message` 的 `begin_nested()` 包住整個流程。唯一例外是 `bulk_insert` 時每個事件開 savepoint 處理 exclusion constraint 錯誤。

3. **`custody_events` 的 `child_id`**：M1.4 全部填 `None`（表示適用所有小孩）。specific_child 的 mapping 留到 M2.1。

4. **counterparty 還沒加入時的處理**：`_resolve_custodian_user_id` 遇到 counterparty 但對方還沒加入，folder back 用 speaker 自己的 id 並在 notes 標註。不要拋錯——單方使用是合法情境。對方加入時，M2.1 會有專門的 user_id reassignment 流程。

5. **exclusion constraint 觸發時**：PostgreSQL 會拋 `IntegrityError`，用 savepoint 隔離後跳過該事件。不要把整個 `bulk_insert` rollback。

6. **`confirm_revocation` 的 timezone**：程式碼裡有 `ZoneInfo("Asia/Taipei")` hardcode，實作時要改成從 case 讀取 `case.timezone`。

7. **audit_log 的 before_state**：撤銷規則時填 `{"revoked": False}`，after 填完整狀態。不需要把整個 rule 物件 dump 進去。

8. **測試的 seeded fixture**：`conftest.py` 的 `seeded_case` 可能需要擴充版本：`seeded_case_with_rule`（已有一條規則與展開事件）、`seeded_case_with_event`（已有一筆單一事件）。這些幫助 integration test 更乾淨。
