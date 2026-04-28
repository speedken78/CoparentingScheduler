import asyncio
import calendar
import hashlib
from datetime import date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML as WeasyHTML

from app.agents.context import _rrule_to_human
from app.config import settings
from app.models.audit_log import AuditAnchor, AuditLog
from app.models.case import CaseMembership, FamilyCase
from app.models.custody_event import CustodyEvent
from app.models.custody_rule import CustodyRule
from app.models.handover import HandoverRecord
from app.models.report import Report
from app.models.user import User
from app.repositories.report_repo import ReportRepository
from app.services.audit_service import log as audit_log

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
TZ = ZoneInfo("Asia/Taipei")

STATUS_LABELS = {
    "scheduled": "排定",
    "confirmed": "已確認",
    "in_progress": "進行中",
    "completed": "已完成",
    "missed": "未出現",
    "disputed": "爭議",
    "cancelled": "已取消",
}

SOURCE_LABELS = {
    "court_order": "法院命令",
    "mutual_agreement": "雙方協議",
    "unilateral": "單方記錄",
}

ACTION_LABELS = {
    "create_custody_rule": "建立規則",
    "update_custody_rule": "修改規則",
    "revoke_custody_rule": "撤銷規則",
    "create_custody_event": "建立事件",
    "update_custody_event": "修改事件",
    "cancel_custody_event": "取消事件",
    "complete_custody_event": "標記完成",
    "create_handover_record": "打卡",
    "confirm_handover_record": "對方確認",
    "propose_revocation": "提案撤銷",
    "agent_tool_call": "AI 解析",
}


async def _fetch_report_data(
    case_id: UUID,
    period_start: date,
    period_end: date,
    requesting_user_id: UUID,
    db: AsyncSession,
) -> dict:
    case = await db.get(FamilyCase, case_id)

    members_result = await db.execute(
        select(CaseMembership, User)
        .join(User, User.id == CaseMembership.user_id)
        .where(
            and_(
                CaseMembership.case_id == case_id,
                CaseMembership.revoked_at.is_(None),
                CaseMembership.relation.in_(["parent_a", "parent_b"]),
            )
        )
    )
    members = members_result.all()

    requesting_user = await db.get(User, requesting_user_id)
    my_name = requesting_user.display_name if requesting_user else "我"
    other_name = None
    for membership, user in members:
        if str(user.id) != str(requesting_user_id):
            other_name = user.display_name
            break

    rules_result = await db.execute(
        select(CustodyRule, User)
        .join(User, User.id == CustodyRule.custodian_id)
        .where(
            and_(
                CustodyRule.case_id == case_id,
                CustodyRule.effective_from <= period_end,
                (CustodyRule.effective_until.is_(None)) |
                (CustodyRule.effective_until >= period_start),
            )
        )
        .order_by(CustodyRule.effective_from.asc())
    )
    rules = []
    for rule, custodian_user in rules_result.all():
        is_me = str(custodian_user.id) == str(requesting_user_id)
        rules.append({
            "custodian_label": "我" if is_me else f"對方（{custodian_user.display_name}）",
            "rrule_human": _rrule_to_human(rule.rrule),
            "start_time": str(rule.start_time)[:5],
            "end_time": str(rule.end_time)[:5],
            "source_label": SOURCE_LABELS.get(rule.source, rule.source),
            "effective_from": str(rule.effective_from),
            "effective_until": str(rule.effective_until) if rule.effective_until else None,
            "revoked": rule.revoked_at is not None,
        })

    period_start_dt = datetime.combine(period_start, datetime.min.time()).replace(tzinfo=TZ)
    period_end_dt = datetime.combine(period_end, datetime.max.time()).replace(tzinfo=TZ)

    events_result = await db.execute(
        select(CustodyEvent, User)
        .join(User, User.id == CustodyEvent.custodian_id)
        .where(
            and_(
                CustodyEvent.case_id == case_id,
                CustodyEvent.deleted_at.is_(None),
                CustodyEvent.starts_at >= period_start_dt,
                CustodyEvent.starts_at <= period_end_dt,
            )
        )
        .order_by(CustodyEvent.starts_at.asc())
    )
    events_raw = events_result.all()

    event_ids = [e.id for e, _ in events_raw]
    handovers_map: dict[UUID, list] = {}
    if event_ids:
        handovers_result = await db.execute(
            select(HandoverRecord)
            .where(HandoverRecord.event_id.in_(event_ids))
            .order_by(HandoverRecord.performed_at.asc())
        )
        for hr in handovers_result.scalars().all():
            handovers_map.setdefault(hr.event_id, []).append(hr)

    events = []
    stats = {
        "my_scheduled_days": 0, "other_scheduled_days": 0,
        "my_completed": 0, "other_completed": 0,
        "my_missed": 0, "other_missed": 0,
        "my_disputed": 0, "other_disputed": 0,
    }
    for event, custodian_user in events_raw:
        is_me = str(custodian_user.id) == str(requesting_user_id)
        prefix = "my" if is_me else "other"

        if event.status in ("scheduled", "confirmed", "completed"):
            stats[f"{prefix}_scheduled_days"] += 1
        if event.status == "completed":
            stats[f"{prefix}_completed"] += 1
        elif event.status == "missed":
            stats[f"{prefix}_missed"] += 1
        elif event.status == "disputed":
            stats[f"{prefix}_disputed"] += 1

        hrs = handovers_map.get(event.id, [])
        handover_time = None
        counterparty_confirmed = False
        if hrs:
            handover_time = hrs[0].performed_at.astimezone(TZ).strftime("%m/%d %H:%M")
            counterparty_confirmed = any(hr.counterparty_confirmed for hr in hrs)

        events.append({
            "date": event.starts_at.astimezone(TZ).strftime("%Y/%m/%d"),
            "start_time": event.starts_at.astimezone(TZ).strftime("%H:%M"),
            "end_time": event.ends_at.astimezone(TZ).strftime("%H:%M"),
            "custodian_label": "我" if is_me else "對方",
            "status": event.status,
            "status_label": STATUS_LABELS.get(event.status, event.status),
            "handover_time": handover_time,
            "counterparty_confirmed": counterparty_confirmed,
            "notes": event.notes,
        })

    audit_result = await db.execute(
        select(AuditLog, User)
        .join(User, User.id == AuditLog.actor_id)
        .where(
            and_(
                AuditLog.case_id == case_id,
                AuditLog.occurred_at >= period_start_dt,
                AuditLog.occurred_at <= period_end_dt,
                AuditLog.action.in_(list(ACTION_LABELS.keys())),
            )
        )
        .order_by(AuditLog.occurred_at.asc())
    )
    audit_changes = []
    for log_row, actor_user in audit_result.all():
        is_me = str(actor_user.id) == str(requesting_user_id)
        audit_changes.append({
            "occurred_at": log_row.occurred_at.astimezone(TZ).strftime("%Y/%m/%d %H:%M"),
            "action_label": ACTION_LABELS.get(log_row.action, log_row.action),
            "actor_label": "我" if is_me else actor_user.display_name,
            "triggered_by_label": "AI" if log_row.triggered_by == "agent" else "人工",
            "summary": _summarize_audit_after_state(log_row.after_state),
        })

    last_audit_result = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    last_audit = last_audit_result.one_or_none()
    last_audit_id = last_audit[0] if last_audit else 0
    last_audit_hash = last_audit[1] if last_audit else "（無稽核紀錄）"

    anchor_result = await db.execute(
        select(AuditAnchor).order_by(AuditAnchor.id.desc()).limit(1)
    )
    last_anchor = anchor_result.scalar_one_or_none()

    return {
        "title": f"監護排程紀錄報告 {period_start}–{period_end}",
        "report_type_label": _report_type_label(period_start, period_end),
        "case_name": case.case_name if case else "",
        "court_case_no": case.court_case_no if case else None,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "generated_at": datetime.now(TZ).strftime("%Y/%m/%d %H:%M"),
        "generated_by_name": my_name,
        "my_name": my_name,
        "other_name": other_name,
        "stats": stats,
        "rules": rules,
        "events": events,
        "audit_changes": audit_changes,
        "last_audit_id": last_audit_id,
        "last_audit_hash": last_audit_hash,
        "anchor_proof": last_anchor.anchor_proof if last_anchor else None,
        "last_anchor_at": (
            last_anchor.anchored_at.astimezone(TZ).strftime("%Y/%m/%d %H:%M")
            if last_anchor else None
        ),
    }


def _report_type_label(period_start: date, period_end: date) -> str:
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    if period_start.day == 1 and period_end == period_start.replace(day=last_day):
        return f"{period_start.year} 年 {period_start.month} 月 月報"
    return f"{period_start} 至 {period_end} 自訂期間報告"


def _summarize_audit_after_state(after_state: dict | None) -> str:
    if not after_state:
        return ""
    parts = []
    if "rrule" in after_state:
        parts.append(f"規則：{_rrule_to_human(after_state['rrule'])}")
    if "starts_at" in after_state:
        parts.append(f"時間：{after_state['starts_at'][:16]}")
    if "reason" in after_state:
        parts.append(f"原因：{after_state['reason']}")
    if "expanded_events_count" in after_state:
        parts.append(f"展開 {after_state['expanded_events_count']} 個事件")
    return "；".join(parts) if parts else str(after_state)[:80]


async def generate_report(
    case_id: UUID,
    period_start: date,
    period_end: date,
    report_type: str,
    requesting_user_id: UUID,
    db: AsyncSession,
) -> Report:
    template_data = await _fetch_report_data(
        case_id, period_start, period_end, requesting_user_id, db
    )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("reports/monthly.html")
    html_content = template.render(**template_data)

    loop = asyncio.get_event_loop()
    weasy_html = WeasyHTML(string=html_content)
    pdf_bytes = await loop.run_in_executor(None, weasy_html.write_pdf)

    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_path = await _store_pdf(case_id, period_start, period_end, pdf_bytes)

    last_audit_result = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    last_audit = last_audit_result.one_or_none()
    last_audit_id = last_audit[0] if last_audit else 0
    last_audit_hash = last_audit[1] if last_audit else ""

    anchor_result = await db.execute(
        select(AuditAnchor.id).order_by(AuditAnchor.id.desc()).limit(1)
    )
    anchor_id = anchor_result.scalar_one_or_none()

    report_repo = ReportRepository(db)
    report = await report_repo.insert({
        "case_id": case_id,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "generated_by": requesting_user_id,
        "pdf_gcs_path": pdf_path,
        "pdf_sha256": pdf_sha256,
        "last_audit_id": last_audit_id,
        "last_audit_hash": last_audit_hash,
        "anchor_id": anchor_id,
    })

    await audit_log(
        db,
        case_id=case_id,
        actor_id=requesting_user_id,
        action="generate_report",
        entity_type="report",
        entity_id=report.id,
        before_state=None,
        after_state={
            "report_type": report_type,
            "period_start": str(period_start),
            "period_end": str(period_end),
            "pdf_sha256": pdf_sha256,
            "last_audit_id": last_audit_id,
        },
        triggered_by="human",
    )

    return report


async def _store_pdf(
    case_id: UUID,
    period_start: date,
    period_end: date,
    pdf_bytes: bytes,
) -> str:
    filename = f"{case_id}_{period_start}_{period_end}.pdf"
    mode = getattr(settings, "PDF_STORAGE_MODE", "local")

    if mode == "gcs":
        from google.cloud import storage as gcs
        client = gcs.Client()
        bucket = client.bucket(settings.GCS_BUCKET_REPORTS)
        path = f"reports/{case_id}/{filename}"
        blob = bucket.blob(path)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        return f"gs://{settings.GCS_BUCKET_REPORTS}/{path}"
    else:
        local_dir = Path("/tmp/reports") / str(case_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / filename
        local_path.write_bytes(pdf_bytes)
        return str(local_path)
