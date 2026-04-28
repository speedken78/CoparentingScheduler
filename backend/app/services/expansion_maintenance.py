import logging
from datetime import date, datetime, timedelta, timezone as dt_tz
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.custody_event import CustodyEvent
from app.models.custody_rule import CustodyRule
from app.utils.rrule_expander import expand_rule

EXPAND_WINDOW_MONTHS = 6

log = logging.getLogger(__name__)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return d.replace(year=year, month=month, day=day)


async def extend_all_active_rules(db: AsyncSession) -> dict:
    """
    遍歷所有未撤銷規則，把展開視窗推進到 today + 6 個月。
    只補展開「尚未有事件的未來日期」，不重複建立。

    回傳：{"processed": int, "new_events": int, "errors": int}
    """
    today = date.today()
    expand_until = _add_months(today, EXPAND_WINDOW_MONTHS)

    rules_result = await db.execute(
        select(CustodyRule).where(CustodyRule.revoked_at.is_(None))
    )
    rules = list(rules_result.scalars().all())

    processed = 0
    new_events = 0
    errors = 0

    for rule in rules:
        try:
            last_event_result = await db.execute(
                select(func.max(CustodyEvent.starts_at))
                .where(
                    and_(
                        CustodyEvent.rule_id == rule.id,
                        CustodyEvent.deleted_at.is_(None),
                    )
                )
            )
            last_event_dt = last_event_result.scalar_one_or_none()

            if last_event_dt:
                from_date = last_event_dt.date() + timedelta(days=1)
            else:
                from_date = max(rule.effective_from, today)

            if from_date > expand_until:
                processed += 1
                continue

            expanded = expand_rule(
                rrule_str=rule.rrule,
                start_time=rule.start_time,
                end_time=rule.end_time,
                effective_from=from_date,
                effective_until=rule.effective_until,
                timezone="Asia/Taipei",
                expand_until=expand_until,
            )

            for e in expanded:
                try:
                    async with db.begin_nested():
                        event = CustodyEvent(
                            case_id=rule.case_id,
                            child_id=rule.child_id,
                            custodian_id=rule.custodian_id,
                            rule_id=rule.id,
                            starts_at=e.starts_at,
                            ends_at=e.ends_at,
                            status="scheduled",
                            created_by=rule.created_by,
                        )
                        db.add(event)
                        await db.flush()
                        new_events += 1
                except Exception:
                    pass

            processed += 1

        except Exception as ex:
            errors += 1
            log.error(f"expansion_maintenance: rule {rule.id} failed: {ex}")

    return {"processed": processed, "new_events": new_events, "errors": errors}
