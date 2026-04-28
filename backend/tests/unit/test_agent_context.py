import pytest
from app.agents.context import _rrule_to_human


@pytest.mark.parametrize("rrule, expected", [
    ("FREQ=WEEKLY;BYDAY=MO,WE,FR", "每週一、週三、週五"),
    ("FREQ=WEEKLY;INTERVAL=2;BYDAY=SA,SU", "隔週週六、週日"),
    ("FREQ=MONTHLY;BYDAY=2SU", "每月第2個週日"),
    ("FREQ=MONTHLY;BYDAY=1SU,3SU,5SU", "每月第1個週日、第3個週日、第5個週日"),
    ("FREQ=DAILY", "FREQ=DAILY"),   # fallback
])
def test_rrule_to_human(rrule, expected):
    assert _rrule_to_human(rrule) == expected


def test_today_label():
    from app.agents.context import AgentContext
    from uuid import uuid4
    ctx = AgentContext(
        session_id=uuid4(), case_id=uuid4(), speaker_user_id=uuid4(),
        case_timezone="Asia/Taipei", active_rules=[], messages=[],
    )
    label = ctx.today_label()
    # 格式：2026-04-21（週二）
    assert "（週" in label
    assert label.count("-") == 2
