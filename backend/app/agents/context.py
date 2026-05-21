# app/agents/context.py
from dataclasses import dataclass, field
from uuid import UUID
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.agent_session import AgentSession, AgentMessage
from app.models.custody_rule import CustodyRule
from app.models.custody_event import CustodyEvent
from app.models.case import CaseMembership


@dataclass
class AgentContext:
    session_id: UUID
    case_id: UUID
    speaker_user_id: UUID          # 目前說話的使用者
    case_timezone: str
    active_rules: list[dict]       # 現有規則摘要（給 system prompt 用）
    messages: list[dict]           # Anthropic API 格式的對話歷史
    upcoming_events: list[dict] = field(default_factory=list)  # 未來 60 天事件摘要
    max_history_turns: int = 20    # 最多保留幾輪（防 context 爆掉）

    def today_label(self) -> str:
        """回傳如『2026-04-21（週二）』的字串。"""
        tz = ZoneInfo(self.case_timezone)
        now = datetime.now(tz)
        weekday_map = {0: "一", 1: "二", 2: "三", 3: "四", 4: "五", 5: "六", 6: "日"}
        return f"{now.strftime('%Y-%m-%d')}（週{weekday_map[now.weekday()]}）"

    def append_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def append_assistant_response(self, content: list) -> None:
        """content 是 Anthropic API response 的 content list（含 text / tool_use blocks）。"""
        self.messages.append({"role": "assistant", "content": content})

    def append_tool_results(self, results: list[dict]) -> None:
        """results 是 tool_result content blocks 的 list。"""
        self.messages.append({"role": "user", "content": results})

    def truncated_messages(self) -> list[dict]:
        """
        若對話超過 max_history_turns 輪，從最舊的開始截掉。
        保留規則：
        - 不能截掉最後一輪（使用者最新輸入）
        - tool_use 和對應的 tool_result 必須成對保留
        """
        if len(self.messages) <= self.max_history_turns * 2:
            return self.messages
        # 截掉最前面的 user+assistant 對
        return self.messages[-(self.max_history_turns * 2):]


async def load_context(
    session_id: UUID,
    case_id: UUID,
    speaker_user_id: UUID,
    db: AsyncSession,
) -> AgentContext:
    """
    從 DB 重建 AgentContext。
    若 session_id 是新建的，messages 為空 list。
    """
    # 1. 取案件時區
    from app.models.case import FamilyCase
    case = await db.get(FamilyCase, case_id)
    case_timezone = case.timezone if case else "Asia/Taipei"

    # 2. 取最近 N 輪的對話歷史
    result = await db.execute(
        select(AgentMessage)
        .where(AgentMessage.session_id == session_id)
        .order_by(AgentMessage.created_at.asc())
    )
    db_messages = result.scalars().all()

    messages = []
    for msg in db_messages:
        content = msg.content   # 已是 JSON，SQLAlchemy JSONB 自動 parse
        messages.append({"role": msg.role if msg.role != "tool_result" else "user",
                         "content": content})

    # 3. 取現有有效規則（最多 10 條，給 system prompt 用）
    membership = await db.execute(
        select(CaseMembership.relation)
        .where(
            and_(
                CaseMembership.case_id == case_id,
                CaseMembership.user_id == speaker_user_id,
                CaseMembership.revoked_at.is_(None),
            )
        )
    )
    speaker_relation = membership.scalar_one_or_none() or "parent_a"

    rules_result = await db.execute(
        select(CustodyRule)
        .where(
            and_(
                CustodyRule.case_id == case_id,
                CustodyRule.revoked_at.is_(None),
            )
        )
        .order_by(CustodyRule.created_at.desc())
        .limit(10)
    )
    rules = rules_result.scalars().all()

    active_rules = []
    for rule in rules:
        is_speaker = (str(rule.custodian_id) == str(speaker_user_id))
        active_rules.append({
            "id": str(rule.id),
            "is_speaker": is_speaker,
            "rrule": rule.rrule,
            "rrule_human": _rrule_to_human(rule.rrule),
            "start_time": str(rule.start_time)[:5],
            "end_time": str(rule.end_time)[:5],
            "effective_from": str(rule.effective_from),
        })

    # 4. 取未來 60 天事件（供 AI 刪除時參考）
    now_utc = datetime.now(timezone.utc)
    end_utc = now_utc + timedelta(days=60)
    events_result = await db.execute(
        select(CustodyEvent)
        .where(
            and_(
                CustodyEvent.case_id == case_id,
                CustodyEvent.deleted_at.is_(None),
                CustodyEvent.starts_at >= now_utc,
                CustodyEvent.starts_at < end_utc,
            )
        )
        .order_by(CustodyEvent.starts_at.asc())
        .limit(30)
    )
    upcoming_events_db = events_result.scalars().all()

    tz = ZoneInfo(case_timezone)
    upcoming_events: list[dict] = []
    for ev in upcoming_events_db:
        is_speaker = str(ev.custodian_id) == str(speaker_user_id)
        starts_local = ev.starts_at.astimezone(tz)
        ends_local = ev.ends_at.astimezone(tz)
        upcoming_events.append({
            "id": str(ev.id),
            "is_speaker": is_speaker,
            "starts_at": starts_local.strftime("%Y-%m-%d %H:%M"),
            "ends_at": ends_local.strftime("%Y-%m-%d %H:%M"),
            "notes": ev.notes or "",
        })

    return AgentContext(
        session_id=session_id,
        case_id=case_id,
        speaker_user_id=speaker_user_id,
        case_timezone=case_timezone,
        active_rules=active_rules,
        upcoming_events=upcoming_events,
        messages=messages,
    )


def _rrule_to_human(rrule: str) -> str:
    """
    把 RRULE 轉成中文摘要，僅供 system prompt 顯示，不做完整解析。
    範例：FREQ=WEEKLY;BYDAY=MO,WE,FR → 每週一三五
    """
    mapping = {
        "MO": "一", "TU": "二", "WE": "三",
        "TH": "四", "FR": "五", "SA": "六", "SU": "日",
    }
    parts = dict(p.split("=", 1) for p in rrule.split(";") if "=" in p)
    freq = parts.get("FREQ", "")
    byday = parts.get("BYDAY", "")
    interval = parts.get("INTERVAL", "1")

    if freq == "WEEKLY":
        days = "、".join(f"週{mapping.get(d.lstrip('0123456789'), d)}"
                         for d in byday.split(",") if d)
        prefix = "隔週" if interval == "2" else "每"
        return f"{prefix}{days}" if days else f"{prefix}（{rrule}）"
    if freq == "MONTHLY":
        days = "、".join(f"第{d[0]}個週{mapping.get(d[1:], d[1:])}"
                         for d in byday.split(",") if d and d[0].isdigit())
        return f"每月{days}" if days else f"每月（{rrule}）"
    return rrule   # fallback：直接顯示原始 RRULE
