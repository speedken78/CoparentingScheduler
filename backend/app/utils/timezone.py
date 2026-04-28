from datetime import datetime
import zoneinfo


def to_tz(dt: datetime, tz_name: str) -> datetime:
    tz = zoneinfo.ZoneInfo(tz_name)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(tz)
    return dt.astimezone(tz)


def now_utc() -> datetime:
    return datetime.now(tz=zoneinfo.ZoneInfo("UTC"))
