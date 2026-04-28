import pytest
from datetime import date, time
from app.utils.rrule_expander import expand_rule


def test_weekly_mwf():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=MO,WE,FR",
        start_time=time(7, 30),
        end_time=time(17, 30),
        effective_from=date(2026, 1, 5),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 18),
    )
    assert len(events) == 6
    assert events[0].starts_at.hour == 7 and events[0].starts_at.minute == 30
    assert events[0].ends_at.hour == 17 and events[0].ends_at.minute == 30
    assert events[0].starts_at.date() == date(2026, 1, 5)
    assert events[-1].starts_at.date() == date(2026, 1, 16)


def test_biweekly_weekend():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU",
        start_time=time(9, 0),
        end_time=time(18, 0),
        effective_from=date(2026, 1, 3),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 31),
    )
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
        effective_until=date(2026, 2, 28),
        timezone="Asia/Taipei",
        expand_until=date(2026, 12, 31),
    )
    assert all(e.starts_at.date() <= date(2026, 2, 28) for e in events)


def test_overnight_event():
    events = expand_rule(
        rrule_str="FREQ=WEEKLY;BYDAY=FR",
        start_time=time(20, 0),
        end_time=time(8, 0),
        effective_from=date(2026, 1, 2),
        effective_until=None,
        timezone="Asia/Taipei",
        expand_until=date(2026, 1, 8),  # Jan 9 超出範圍，只展開 Jan 2 一筆
    )
    assert len(events) == 1
    assert events[0].ends_at.date() == date(2026, 1, 3)
