from datetime import date


def test_report_type_label_monthly():
    from app.services.report_service import _report_type_label
    label = _report_type_label(date(2026, 4, 1), date(2026, 4, 30))
    assert "4 月" in label and "月報" in label


def test_report_type_label_custom():
    from app.services.report_service import _report_type_label
    label = _report_type_label(date(2026, 4, 1), date(2026, 5, 15))
    assert "自訂" in label


def test_summarize_audit_after_state_rule():
    from app.services.report_service import _summarize_audit_after_state
    s = _summarize_audit_after_state({
        "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR",
        "expanded_events_count": 24,
    })
    assert "每週" in s
    assert "24" in s


def test_summarize_audit_after_state_empty():
    from app.services.report_service import _summarize_audit_after_state
    assert _summarize_audit_after_state(None) == ""
