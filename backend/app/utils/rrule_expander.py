from datetime import datetime, date, time, timedelta
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr


@dataclass
class ExpandedEvent:
    starts_at: datetime
    ends_at: datetime


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
    将 iCal RRULE 展开成具体事件清单。

    Raises:
        ValueError: rrule_str 无效
    """
    tz = ZoneInfo(timezone)
    dtstart = datetime.combine(effective_from, start_time, tzinfo=tz)

    hard_until_date = min(effective_until, expand_until) if effective_until else expand_until
    until_dt = datetime.combine(hard_until_date, time(23, 59, 59), tzinfo=tz)

    try:
        rule = rrulestr(rrule_str, dtstart=dtstart)
    except Exception as e:
        raise ValueError(f"Invalid RRULE: {rrule_str}") from e

    events: list[ExpandedEvent] = []
    for occurrence in rule:
        if occurrence > until_dt:
            break
        day = occurrence.date()
        starts_at = datetime.combine(day, start_time, tzinfo=tz)
        ends_at = datetime.combine(day, end_time, tzinfo=tz)
        if ends_at <= starts_at:
            ends_at = ends_at + timedelta(days=1)
        events.append(ExpandedEvent(starts_at=starts_at, ends_at=ends_at))

    return events
