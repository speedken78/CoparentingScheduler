import calendar
from datetime import datetime, timedelta, time as dtime, date as ddate, timezone as dt_tz
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.agents.context import AgentContext
from app.models.case import CaseMembership
from app.models.custody_event import CustodyEvent
from app.repositories.rule_repo import RuleRepository
from app.repositories.event_repo import EventRepository
from app.repositories.revocation_proposal_repo import RevocationProposalRepository
from app.services.audit_service import log as audit_log
from app.utils.rrule_expander import expand_rule

EXPAND_WINDOW_MONTHS = 6


def _parse_time(time_str: str) -> dtime:
    """Parse ISO time string; converts 24:00[:00] (end-of-day) to 00:00."""
    if time_str.startswith("24:"):
        time_str = "00:" + time_str[3:]
    return dtime.fromisoformat(time_str)


# ── 衝突偵測（M1.3 保留）────────────────────────────────────────────────────

async def detect_conflicts(
    ctx: AgentContext,
    tool_input: dict,
    db: AsyncSession,
) -> list[dict]:
    conflicts = []
    intent = tool_input.get("intent")
    case_tz = ZoneInfo(ctx.case_timezone)

    if intent == "create_one_time_event":
        starts_at = datetime.fromisoformat(tool_input["starts_at"])
        ends_at = datetime.fromisoformat(tool_input["ends_at"])
        conflicts = await _check_event_conflicts(ctx.case_id, starts_at, ends_at, db)

    elif intent == "create_recurring_rule":
        rrule_str = tool_input.get("rrule", "")
        start_time_str = tool_input.get("start_time", "09:00")
        end_time_str = tool_input.get("end_time", "18:00")
        effective_from = tool_input.get("effective_from", "")

        if rrule_str and effective_from:
            try:
                from dateutil.rrule import rrulestr
                dtstart = datetime.fromisoformat(effective_from).replace(tzinfo=case_tz)
                until = dtstart + timedelta(days=90)
                rule = rrulestr(rrule_str, dtstart=dtstart)
                h_start, m_start = map(int, start_time_str.split(":"))
                h_end, m_end = map(int, end_time_str.split(":"))

                for dt in rule:
                    if dt > until:
                        break
                    event_start = dt.replace(hour=h_start, minute=m_start, tzinfo=case_tz)
                    event_end = dt.replace(hour=h_end, minute=m_end, tzinfo=case_tz)
                    day_conflicts = await _check_event_conflicts(
                        ctx.case_id, event_start, event_end, db
                    )
                    conflicts.extend(day_conflicts)
                    if len(conflicts) >= 5:
                        break
            except Exception:
                pass

    return conflicts


async def _check_event_conflicts(
    case_id,
    starts_at: datetime,
    ends_at: datetime,
    db: AsyncSession,
) -> list[dict]:
    result = await db.execute(
        select(CustodyEvent)
        .where(
            and_(
                CustodyEvent.case_id == case_id,
                CustodyEvent.deleted_at.is_(None),
                CustodyEvent.status != "cancelled",
                CustodyEvent.starts_at < ends_at,
                CustodyEvent.ends_at > starts_at,
            )
        )
        .limit(5)
    )
    events = result.scalars().all()
    return [
        {
            "event_id": str(e.id),
            "starts_at": e.starts_at.isoformat(),
            "ends_at": e.ends_at.isoformat(),
            "status": e.status,
        }
        for e in events
    ]


# ── 真實實作 ──────────────────────────────────────────────────────────────────

async def _resolve_custodian_user_id(
    ctx: AgentContext,
    custodian_label: str,
    db: AsyncSession,
) -> UUID:
    if custodian_label == "speaker":
        return ctx.speaker_user_id

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
        # 對方尚未加入，用 speaker id 作為 placeholder，M2.1 處理替換
        return ctx.speaker_user_id
    return member.user_id


async def create_rule(ctx: AgentContext, tool_input: dict, db: AsyncSession) -> dict:
    rule_repo = RuleRepository(db)
    event_repo = EventRepository(db)

    custodian_id = await _resolve_custodian_user_id(ctx, tool_input["custodian"], db)
    is_counterparty_placeholder = (
        tool_input["custodian"] == "counterparty" and custodian_id == ctx.speaker_user_id
    )

    start_time = _parse_time(tool_input["start_time"])
    end_time = _parse_time(tool_input["end_time"])
    effective_from = ddate.fromisoformat(tool_input["effective_from"])
    effective_until = (
        ddate.fromisoformat(tool_input["effective_until"])
        if tool_input.get("effective_until") else None
    )

    rrule_str = tool_input["rrule"]

    notes_text = tool_input.get("reasoning", "")
    if is_counterparty_placeholder:
        notes_text = f"[counterparty placeholder] {notes_text}"

    rule_data = {
        "case_id": ctx.case_id,
        "child_id": None,
        "custodian_id": custodian_id,
        "rule_type": _infer_rule_type(rrule_str),
        "rrule": rrule_str,
        "start_time": start_time,
        "end_time": end_time,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "priority": 100,
        "source": tool_input.get("source", "unilateral"),
        "notes": notes_text,
        "created_by": ctx.speaker_user_id,
    }
    rule = await rule_repo.insert(rule_data)

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

    inserted_events = []
    skipped_count = 0
    for event_data in events_data:
        try:
            async with db.begin_nested():
                e = await event_repo.bulk_insert([event_data])
                inserted_events.extend(e)
        except Exception:
            skipped_count += 1

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


async def create_event(ctx: AgentContext, tool_input: dict, db: AsyncSession) -> dict:
    event_repo = EventRepository(db)

    custodian_id = await _resolve_custodian_user_id(ctx, tool_input["custodian"], db)

    starts_at = datetime.fromisoformat(tool_input["starts_at"])
    ends_at = datetime.fromisoformat(tool_input["ends_at"])

    conflicts = await _check_event_conflicts(ctx.case_id, starts_at, ends_at, db)
    if conflicts:
        return {
            "status": "conflict_blocked",
            "message": "此時段與現有事件重疊，無法建立",
        }

    event_data = {
        "case_id": ctx.case_id,
        "child_id": None,
        "custodian_id": custodian_id,
        "rule_id": None,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "scheduled",
        "handover_location": tool_input.get("handover_location"),
        "notes": tool_input.get("notes") or tool_input.get("reasoning", ""),
        "created_by": ctx.speaker_user_id,
    }

    try:
        async with db.begin_nested():
            events = await event_repo.bulk_insert([event_data])
            event = events[0]
    except Exception:
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


async def delete_event(ctx: AgentContext, tool_input: dict, db: AsyncSession) -> dict:
    from uuid import UUID as _UUID
    event_repo = EventRepository(db)

    try:
        event_id = _UUID(tool_input["event_id"])
    except (ValueError, KeyError):
        return {"status": "error", "message": "無效的 event_id"}

    event = await event_repo.soft_delete(event_id, ctx.case_id)
    if event is None:
        return {"status": "not_found", "message": "找不到該事件，或已刪除"}

    await audit_log(
        db,
        case_id=ctx.case_id,
        actor_id=ctx.speaker_user_id,
        action="delete_custody_event",
        entity_type="custody_event",
        entity_id=event_id,
        before_state={"starts_at": event.starts_at.isoformat(), "ends_at": event.ends_at.isoformat()},
        after_state={"deleted": True, "reason": tool_input.get("reason", "")},
        triggered_by="agent",
        agent_session_id=ctx.session_id,
    )

    return {
        "status": "deleted",
        "event_id": str(event_id),
        "summary": f"已刪除事件：{event.starts_at.strftime('%Y-%m-%d %H:%M')}",
    }


async def propose_revocation(
    ctx: AgentContext, tool_input: dict, db: AsyncSession
) -> dict:
    proposal_repo = RevocationProposalRepository(db)

    rule_id = await _find_rule_by_hint(ctx, tool_input["rule_hint"], db)

    proposal = await proposal_repo.insert({
        "case_id": ctx.case_id,
        "rule_id": rule_id,
        "rule_hint": tool_input["rule_hint"],
        "revocation_reason": tool_input.get("revocation_reason", "使用者要求撤銷"),
        "effective_from": ddate.today(),
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
            "reason": tool_input.get("revocation_reason", "使用者要求撤銷"),
        },
        triggered_by="agent",
        agent_session_id=ctx.session_id,
    )

    return {
        "id": proposal.id,
        "rule_matched": rule_id is not None,
        "rule_id": str(rule_id) if rule_id else None,
    }


async def confirm_revocation(
    proposal_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    user=None,
) -> dict:
    proposal_repo = RevocationProposalRepository(db)
    rule_repo = RuleRepository(db)
    event_repo = EventRepository(db)

    proposal = await proposal_repo.get_by_id(proposal_id)
    if not proposal or proposal.status != "pending":
        raise ValueError("Proposal not found or not pending")

    if not proposal.rule_id:
        raise ValueError("Proposal has no matched rule; cannot confirm automatically")

    rule = await rule_repo.revoke(
        rule_id=proposal.rule_id,
        revoked_by=user_id,
        revoked_reason=proposal.revocation_reason,
        revoked_at_date=proposal.effective_from,
    )
    if not rule:
        raise ValueError("Rule already revoked or not found")

    # 取案件時區（從 rule 所屬 case）
    from app.models.case import FamilyCase
    case = await db.get(FamilyCase, proposal.case_id)
    tz_name = case.timezone if case else "Asia/Taipei"
    tz = ZoneInfo(tz_name)
    cutoff = datetime.combine(proposal.effective_from, dtime(0, 0), tzinfo=tz)

    # 取出要刪除的事件，先清除 GCal（若 user 有授權）
    if user is None:
        from app.models.user import User as UserModel
        user = await db.get(UserModel, user_id)
    if user is not None:
        from app.services.gcal_sync_service import delete_gcal_event
        events_to_delete = await event_repo.list_scheduled_after(proposal.rule_id, cutoff)
        for ev in events_to_delete:
            await delete_gcal_event(ev, user, db)

    deleted_count = await event_repo.delete_scheduled_by_rule_after(
        rule_id=proposal.rule_id,
        after=cutoff,
    )

    proposal.status = "confirmed"
    proposal.confirmed_at = datetime.now(dt_tz.utc)
    proposal.confirmed_by = user_id
    await db.flush()

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


async def _find_rule_by_hint(
    ctx: AgentContext, hint: str, db: AsyncSession
) -> UUID | None:
    rules = await RuleRepository(db).list_active(ctx.case_id)
    if not rules:
        return None

    weekday_map = {
        "一": "MO", "二": "TU", "三": "WE",
        "四": "TH", "五": "FR", "六": "SA", "日": "SU",
    }
    mentioned_days = [
        code for zh, code in weekday_map.items()
        if f"週{zh}" in hint or f"星期{zh}" in hint
    ]
    if not mentioned_days:
        return None

    for rule in rules:
        if all(d in rule.rrule for d in mentioned_days):
            return rule.id
    return None


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
    from app.agents.context import _rrule_to_human
    return _rrule_to_human(rrule)


def _add_months(d: ddate, months: int) -> ddate:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return ddate(year, month, min(d.day, last_day))
