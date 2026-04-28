# MILESTONE_1_6.md｜PDF 報告生成

> 閱讀順序：本文件 → DATABASE.md（reports 表、audit_log）→ ARCHITECTURE.md §4（PDF 報告說明）
> 完成後跑 §9 DoD，全部通過才算完成。

---

## 0. 本 Milestone 的交付範圍

| 交付項目 | 說明 |
|---|---|
| `Dockerfile` 更新 | 加入 WeasyPrint 系統依賴 |
| `app/templates/reports/monthly.html` | 月報 HTML 模板 |
| `app/templates/reports/base.html` | 共用樣式（含中文字型） |
| `app/services/report_service.py` | PDF 生成主體 |
| `app/repositories/report_repo.py` | Report CRUD |
| Migration 013 | `reports` 表（DATABASE.md §2.9 已定義，補 migration） |
| `app/api/v1/reports.py` | REST endpoints |
| `tests/unit/test_report_service.py` | HTML 渲染與 PDF 生成測試 |
| `tests/integration/test_reports.py` | 端到端：建規則 → 打卡 → 產報告 |

---

## 1. Dockerfile 更新（必須第一步做）

`python:3.12-slim` 缺少 WeasyPrint 需要的 Cairo、Pango、GDK-Pixbuf。
替換現有 Dockerfile：

```dockerfile
FROM python:3.12-slim

# WeasyPrint 系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Cairo（向量繪圖）
    libcairo2 \
    libcairo2-dev \
    # Pango（文字排版，中文必要）
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    # GDK-Pixbuf（圖片處理）
    libgdk-pixbuf2.0-0 \
    # 中文字型：Noto Sans CJK TC
    fonts-noto-cjk \
    # 其他依賴
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libopenjp2-7 \
    # 清理
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir hatchling
# （其餘 Dockerfile 內容保留不變）
```

**驗證安裝**：
```bash
docker compose build api
docker compose run --rm api python -c "import weasyprint; print(weasyprint.__version__)"
```
若無錯誤才繼續後面的步驟。

---

## 2. 新增套件

```toml
# pyproject.toml 新增
weasyprint = "^62.0"
jinja2 = "^3.1"       # HTML 模板引擎（FastAPI 已依賴，確認版本即可）
```

---

## 3. Migration 013（reports 表）

DATABASE.md §2.9 已定義欄位，建立 `alembic/versions/013_reports.py`：

```python
"""013: reports table

Revision ID: 013
Revises: 012
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.execute("""
        CREATE TABLE reports (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            case_id         UUID NOT NULL REFERENCES family_cases(id),
            report_type     TEXT NOT NULL
                            CHECK (report_type IN
                                ('monthly','custom_range','dispute','full_history')),
            period_start    DATE NOT NULL,
            period_end      DATE NOT NULL,
            generated_by    UUID NOT NULL REFERENCES users(id),
            generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            pdf_gcs_path    TEXT NOT NULL,
            pdf_sha256      TEXT NOT NULL,
            last_audit_id   BIGINT NOT NULL,
            last_audit_hash TEXT NOT NULL,
            anchor_id       BIGINT REFERENCES audit_anchors(id)
        );

        CREATE INDEX idx_reports_case ON reports(case_id, generated_at DESC);

        ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
        ALTER TABLE reports FORCE ROW LEVEL SECURITY;

        CREATE POLICY reports_case_isolation ON reports
            FOR ALL
            USING (case_id = ANY(get_user_case_ids()));

        GRANT SELECT, INSERT ON reports TO app_role;
    """)

def downgrade():
    op.execute("DROP TABLE IF EXISTS reports CASCADE;")
```

---

## 4. HTML 模板

### 4.1 目錄結構

```
app/templates/reports/
├── base.html       # 共用：CSS、字型、頁首頁尾
└── monthly.html    # 月報主體（繼承 base）
```

### 4.2 `base.html`

```html
<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>{{ title }}</title>
<style>
  /* ── 字型 ── */
  @font-face {
    font-family: 'NotoSansCJK';
    src: url('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc') format('truetype');
    font-weight: normal;
  }
  @font-face {
    font-family: 'NotoSansCJK';
    src: url('/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc') format('truetype');
    font-weight: bold;
  }

  /* ── 全域 ── */
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'NotoSansCJK', 'Noto Sans CJK TC', sans-serif;
    font-size: 10pt;
    line-height: 1.6;
    color: #1a1a1a;
    background: white;
  }

  /* ── 頁面設定 ── */
  @page {
    size: A4;
    margin: 2cm 2.5cm 2.5cm 2.5cm;
    @bottom-center {
      content: "第 " counter(page) " 頁，共 " counter(pages) " 頁";
      font-family: 'NotoSansCJK', sans-serif;
      font-size: 8pt;
      color: #888;
    }
    @top-right {
      content: "{{ case_name }} ｜ 共親職排程紀錄";
      font-family: 'NotoSansCJK', sans-serif;
      font-size: 8pt;
      color: #888;
    }
  }

  /* ── 封面 ── */
  .cover {
    page-break-after: always;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 240mm;
    text-align: center;
  }
  .cover .logo { font-size: 14pt; color: #4a6fa5; margin-bottom: 16pt; }
  .cover h1 { font-size: 20pt; font-weight: bold; margin-bottom: 8pt; }
  .cover .subtitle { font-size: 12pt; color: #555; margin-bottom: 32pt; }
  .cover .meta-table { margin: 0 auto; text-align: left; }
  .cover .meta-table td { padding: 3pt 12pt 3pt 0; }
  .cover .meta-table .label { color: #888; }
  .cover .integrity-box {
    margin-top: 32pt;
    padding: 12pt;
    border: 1pt solid #d0d0d0;
    background: #f8f8f8;
    font-size: 8pt;
    color: #555;
    text-align: left;
    word-break: break-all;
  }

  /* ── 區塊標題 ── */
  h2 {
    font-size: 13pt;
    font-weight: bold;
    color: #4a6fa5;
    border-bottom: 1.5pt solid #4a6fa5;
    padding-bottom: 4pt;
    margin: 18pt 0 10pt 0;
  }
  h3 { font-size: 11pt; font-weight: bold; margin: 12pt 0 6pt 0; }

  /* ── 表格 ── */
  table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 12pt;
    font-size: 9pt;
  }
  thead th {
    background: #4a6fa5;
    color: white;
    padding: 5pt 8pt;
    text-align: left;
    font-weight: bold;
  }
  tbody tr:nth-child(even) { background: #f2f6fb; }
  tbody td { padding: 4pt 8pt; border-bottom: 0.5pt solid #e0e0e0; }

  /* ── 狀態標籤 ── */
  .badge {
    display: inline-block;
    padding: 1pt 5pt;
    border-radius: 3pt;
    font-size: 8pt;
    font-weight: bold;
  }
  .badge-completed { background: #d4edda; color: #155724; }
  .badge-missed    { background: #f8d7da; color: #721c24; }
  .badge-disputed  { background: #fff3cd; color: #856404; }
  .badge-scheduled { background: #e2e3e5; color: #383d41; }
  .badge-cancelled { background: #e2e3e5; color: #6c757d; }

  /* ── 免責聲明 ── */
  .disclaimer {
    margin-top: 24pt;
    padding: 10pt;
    border-left: 3pt solid #f0ad4e;
    background: #fffbf0;
    font-size: 8pt;
    color: #666;
  }

  /* ── 分頁 ── */
  .page-break { page-break-before: always; }
</style>
</head>
<body>
{% block content %}{% endblock %}
</body>
</html>
```

### 4.3 `monthly.html`

```html
{% extends "reports/base.html" %}
{% block content %}

{# ── 封面 ── #}
<div class="cover">
  <div class="logo">⚖ 共親職排程系統</div>
  <h1>監護排程紀錄報告</h1>
  <div class="subtitle">{{ report_type_label }}</div>
  <table class="meta-table">
    <tr>
      <td class="label">案件名稱</td>
      <td>{{ case_name }}</td>
    </tr>
    <tr>
      <td class="label">法院案號</td>
      <td>{{ court_case_no or "（未填）" }}</td>
    </tr>
    <tr>
      <td class="label">紀錄期間</td>
      <td>{{ period_start }} 至 {{ period_end }}</td>
    </tr>
    <tr>
      <td class="label">報告產生時間</td>
      <td>{{ generated_at }}</td>
    </tr>
    <tr>
      <td class="label">產生者</td>
      <td>{{ generated_by_name }}</td>
    </tr>
  </table>

  <div class="integrity-box">
    <strong>稽核完整性</strong><br>
    最後稽核 ID：{{ last_audit_id }}<br>
    稽核雜湊：{{ last_audit_hash }}<br>
    {% if anchor_proof %}
    錨定位置：{{ anchor_proof }}
    {% else %}
    錨定：尚未錨定（最近一次錨定時間：{{ last_anchor_at or "無" }}）
    {% endif %}
  </div>
</div>

{# ── 摘要統計 ── #}
<h2>一、期間摘要</h2>
<table>
  <thead>
    <tr>
      <th>統計項目</th>
      <th>我（{{ my_name }}）</th>
      <th>對方（{{ other_name or "未加入" }}）</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>排定監護天數</td>
      <td>{{ stats.my_scheduled_days }} 天</td>
      <td>{{ stats.other_scheduled_days }} 天</td>
    </tr>
    <tr>
      <td>實際完成次數</td>
      <td>{{ stats.my_completed }}</td>
      <td>{{ stats.other_completed }}</td>
    </tr>
    <tr>
      <td>未出現次數（missed）</td>
      <td>{{ stats.my_missed }}</td>
      <td>{{ stats.other_missed }}</td>
    </tr>
    <tr>
      <td>爭議次數</td>
      <td>{{ stats.my_disputed }}</td>
      <td>{{ stats.other_disputed }}</td>
    </tr>
  </tbody>
</table>

{# ── 監護規則 ── #}
<h2>二、本期有效監護規則</h2>
{% if rules %}
<table>
  <thead>
    <tr>
      <th>監護方</th>
      <th>規則說明</th>
      <th>時間</th>
      <th>來源</th>
      <th>生效期間</th>
    </tr>
  </thead>
  <tbody>
    {% for rule in rules %}
    <tr>
      <td>{{ rule.custodian_label }}</td>
      <td>{{ rule.rrule_human }}</td>
      <td>{{ rule.start_time }}–{{ rule.end_time }}</td>
      <td>{{ rule.source_label }}</td>
      <td>{{ rule.effective_from }}
        {% if rule.effective_until %} 至 {{ rule.effective_until }}{% endif %}
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p>本期無有效監護規則。</p>
{% endif %}

{# ── 實際接送紀錄 ── #}
<div class="page-break"></div>
<h2>三、實際接送紀錄</h2>
{% if events %}
<table>
  <thead>
    <tr>
      <th>日期</th>
      <th>時段</th>
      <th>監護方</th>
      <th>狀態</th>
      <th>打卡時間</th>
      <th>對方確認</th>
      <th>備註</th>
    </tr>
  </thead>
  <tbody>
    {% for event in events %}
    <tr>
      <td>{{ event.date }}</td>
      <td>{{ event.start_time }}–{{ event.end_time }}</td>
      <td>{{ event.custodian_label }}</td>
      <td>
        <span class="badge badge-{{ event.status }}">
          {{ event.status_label }}
        </span>
      </td>
      <td>{{ event.handover_time or "—" }}</td>
      <td>{{ "✓" if event.counterparty_confirmed else "—" }}</td>
      <td>{{ event.notes or "" }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p>本期無接送紀錄。</p>
{% endif %}

{# ── 異動紀錄 ── #}
<div class="page-break"></div>
<h2>四、規則異動紀錄</h2>
{% if audit_changes %}
<table>
  <thead>
    <tr>
      <th>時間</th>
      <th>操作</th>
      <th>操作者</th>
      <th>來源</th>
      <th>說明</th>
    </tr>
  </thead>
  <tbody>
    {% for log in audit_changes %}
    <tr>
      <td>{{ log.occurred_at }}</td>
      <td>{{ log.action_label }}</td>
      <td>{{ log.actor_label }}</td>
      <td>{{ log.triggered_by_label }}</td>
      <td>{{ log.summary }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p>本期無規則異動。</p>
{% endif %}

{# ── 免責聲明 ── #}
<div class="disclaimer">
  <strong>免責聲明：</strong>
  本報告由共親職排程系統自動產生，僅供參考及記錄用途，不構成法律意見。
  稽核雜湊值代表本報告產生時的資料完整性，如需法院使用，建議由律師確認其證據效力。
  系統技術支援：請洽應用程式管理員。
</div>

{% endblock %}
```

---

## 5. Report Service（`app/services/report_service.py`）

### 5.1 資料查詢與組裝

```python
# app/services/report_service.py
import hashlib
import io
from datetime import date, datetime, timezone as dt_tz
from uuid import UUID
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML as WeasyHTML
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.family_case import FamilyCase
from app.models.user import User
from app.models.custody_rule import CustodyRule
from app.models.custody_event import CustodyEvent
from app.models.handover_record import HandoverRecord
from app.models.audit_log import AuditLog
from app.models.audit_anchor import AuditAnchor
from app.models.report import Report
from app.repositories.report_repo import ReportRepository
from app.services.audit_service import log as audit_log
from app.agents.context import _rrule_to_human
from app.config import settings

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

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
    """查詢並組裝模板所需的所有資料。"""
    tz_str = "Asia/Taipei"
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_str)

    # 案件基本資料
    case = await db.get(FamilyCase, case_id)

    # 成員
    from app.models.case_membership import CaseMembership
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

    # 本期有效規則（effective_from <= period_end AND (effective_until IS NULL OR >= period_start)）
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
    rules_raw = rules_result.all()

    rules = []
    for rule, custodian_user in rules_raw:
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

    # 本期事件
    from datetime import datetime as dt
    period_start_dt = dt.combine(period_start, dt.min.time()).replace(tzinfo=tz)
    period_end_dt = dt.combine(period_end, dt.max.time()).replace(tzinfo=tz)

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

    # 取打卡紀錄
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

        # 統計
        if event.status in ("scheduled", "confirmed", "completed"):
            stats[f"{prefix}_scheduled_days"] += 1
        if event.status == "completed":
            stats[f"{prefix}_completed"] += 1
        elif event.status == "missed":
            stats[f"{prefix}_missed"] += 1
        elif event.status == "disputed":
            stats[f"{prefix}_disputed"] += 1

        # 打卡時間
        hrs = handovers_map.get(event.id, [])
        handover_time = None
        counterparty_confirmed = False
        if hrs:
            # 取最早一筆打卡時間
            handover_time = hrs[0].performed_at.astimezone(tz).strftime("%m/%d %H:%M")
            counterparty_confirmed = any(hr.counterparty_confirmed for hr in hrs)

        events.append({
            "date": event.starts_at.astimezone(tz).strftime("%Y/%m/%d"),
            "start_time": event.starts_at.astimezone(tz).strftime("%H:%M"),
            "end_time": event.ends_at.astimezone(tz).strftime("%H:%M"),
            "custodian_label": "我" if is_me else "對方",
            "status": event.status,
            "status_label": STATUS_LABELS.get(event.status, event.status),
            "handover_time": handover_time,
            "counterparty_confirmed": counterparty_confirmed,
            "notes": event.notes,
        })

    # 本期 audit_log（排程相關的異動）
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
            "occurred_at": log_row.occurred_at.astimezone(tz).strftime("%Y/%m/%d %H:%M"),
            "action_label": ACTION_LABELS.get(log_row.action, log_row.action),
            "actor_label": "我" if is_me else actor_user.display_name,
            "triggered_by_label": "AI" if log_row.triggered_by == "agent" else "人工",
            "summary": _summarize_audit_after_state(log_row.after_state),
        })

    # 稽核完整性資訊
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
        select(AuditAnchor)
        .order_by(AuditAnchor.id.desc())
        .limit(1)
    )
    last_anchor = anchor_result.scalar_one_or_none()

    return {
        "title": f"監護排程紀錄報告 {period_start}–{period_end}",
        "report_type_label": _report_type_label(period_start, period_end),
        "case_name": case.case_name if case else "",
        "court_case_no": case.court_case_no if case else None,
        "period_start": str(period_start),
        "period_end": str(period_end),
        "generated_at": datetime.now(tz).strftime("%Y/%m/%d %H:%M"),
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
            last_anchor.anchored_at.astimezone(tz).strftime("%Y/%m/%d %H:%M")
            if last_anchor else None
        ),
    }


def _report_type_label(period_start: date, period_end: date) -> str:
    if period_start.day == 1 and period_end == period_start.replace(
        day=__import__('calendar').monthrange(period_start.year, period_start.month)[1]
    ):
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
```

### 5.2 PDF 生成主函數

```python
async def generate_report(
    case_id: UUID,
    period_start: date,
    period_end: date,
    report_type: str,
    requesting_user_id: UUID,
    db: AsyncSession,
) -> Report:
    """
    生成 PDF 報告，存 GCS（或本地 fallback），寫 reports 表。
    回傳 Report ORM 物件。
    """
    # 1. 查詢資料
    template_data = await _fetch_report_data(
        case_id, period_start, period_end, requesting_user_id, db
    )

    # 2. 渲染 HTML
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("reports/monthly.html")
    html_content = template.render(**template_data)

    # 3. 生成 PDF（WeasyPrint）
    pdf_bytes = WeasyHTML(string=html_content).write_pdf()

    # 4. 計算 SHA-256
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    # 5. 儲存 PDF（GCS 或本地，依環境變數決定）
    pdf_path = await _store_pdf(case_id, period_start, period_end, pdf_bytes)

    # 6. 查最後的 audit_log id/hash
    last_audit_result = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    last_audit = last_audit_result.one_or_none()
    last_audit_id = last_audit[0] if last_audit else 0
    last_audit_hash = last_audit[1] if last_audit else ""

    # 7. 查最近的 anchor
    anchor_result = await db.execute(
        select(AuditAnchor.id).order_by(AuditAnchor.id.desc()).limit(1)
    )
    anchor_id = anchor_result.scalar_one_or_none()

    # 8. 寫 reports 表
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

    # 9. audit_log
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
    """
    儲存 PDF。
    PDF_STORAGE_MODE=local → 存到 /tmp/reports/（開發用）
    PDF_STORAGE_MODE=gcs   → 存到 GCS（Production）
    回傳路徑字串。
    """
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
        # 本地開發：存到 /tmp/reports/
        import os
        local_dir = Path("/tmp/reports") / str(case_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / filename
        local_path.write_bytes(pdf_bytes)
        return str(local_path)
```

---

## 6. Repository（`app/repositories/report_repo.py`）

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.report import Report


class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def insert(self, data: dict) -> Report:
        report = Report(**data)
        self.db.add(report)
        await self.db.flush()
        return report

    async def list_by_case(self, case_id: UUID) -> list[Report]:
        result = await self.db.execute(
            select(Report)
            .where(Report.case_id == case_id)
            .order_by(Report.generated_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, report_id: UUID) -> Report | None:
        return await self.db.get(Report, report_id)
```

---

## 7. REST Endpoints（`app/api/v1/reports.py`）

```python
# app/api/v1/reports.py
from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_db
from app.models.user import User
from app.repositories.report_repo import ReportRepository
from app.repositories.membership_repo import MembershipRepository
from app.services.report_service import generate_report

router = APIRouter(prefix="/cases/{case_id}/reports", tags=["reports"])


async def _require_member(case_id: UUID, user_id: UUID, db: AsyncSession):
    m = await MembershipRepository(db).get(case_id, user_id)
    if not m:
        raise HTTPException(403, detail="您不是此案件的成員")
    return m


class GenerateReportRequest(BaseModel):
    period_start: date
    period_end: date
    report_type: str = "monthly"    # monthly / custom_range / dispute / full_history


@router.post("/", status_code=201)
async def create_report(
    case_id: UUID,
    body: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """產生 PDF 報告（同步，可能需要數秒）。"""
    await _require_member(case_id, current_user.id, db)

    if body.period_end < body.period_start:
        raise HTTPException(422, detail="period_end 不可早於 period_start")
    if body.report_type not in ("monthly", "custom_range", "dispute", "full_history"):
        raise HTTPException(422, detail="無效的 report_type")

    async with db.begin_nested():
        report = await generate_report(
            case_id=case_id,
            period_start=body.period_start,
            period_end=body.period_end,
            report_type=body.report_type,
            requesting_user_id=current_user.id,
            db=db,
        )

    return {
        "id": str(report.id),
        "pdf_path": report.pdf_gcs_path,
        "pdf_sha256": report.pdf_sha256,
        "last_audit_id": report.last_audit_id,
        "last_audit_hash": report.last_audit_hash,
        "generated_at": report.generated_at.isoformat(),
    }


@router.get("/")
async def list_reports(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _require_member(case_id, current_user.id, db)
    reports = await ReportRepository(db).list_by_case(case_id)
    return {
        "items": [
            {
                "id": str(r.id),
                "report_type": r.report_type,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "pdf_sha256": r.pdf_sha256,
                "generated_at": r.generated_at.isoformat(),
            }
            for r in reports
        ]
    }


@router.get("/{report_id}/download")
async def download_report(
    case_id: UUID,
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    回傳 PDF 位元組（local 模式直接讀檔；GCS 模式回傳 signed URL）。
    MVP 只實作 local 模式。
    """
    await _require_member(case_id, current_user.id, db)
    report = await ReportRepository(db).get_by_id(report_id)
    if not report or str(report.case_id) != str(case_id):
        raise HTTPException(404, detail="報告不存在")

    from pathlib import Path
    from app.config import settings
    mode = getattr(settings, "PDF_STORAGE_MODE", "local")

    if mode == "local":
        pdf_path = Path(report.pdf_gcs_path)
        if not pdf_path.exists():
            raise HTTPException(404, detail="PDF 檔案不存在（可能已清除）")
        pdf_bytes = pdf_path.read_bytes()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="report_{report.period_start}_{report.period_end}.pdf"'
                )
            },
        )
    else:
        # GCS：產生 signed URL（M1.7 實作完整版）
        raise HTTPException(501, detail="GCS 下載尚未實作")
```

**在 `app/main.py` 新增**：
```python
from app.api.v1 import reports
app.include_router(reports.router, prefix="/api/v1")
```

**`.env.example` 新增**：
```
PDF_STORAGE_MODE=local    # local | gcs
GCS_BUCKET_REPORTS=coparenting-reports
```

---

## 8. 測試

### 8.1 Unit tests（`tests/unit/test_report_service.py`）

```python
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


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


@pytest.mark.asyncio
async def test_html_render_no_crash(seeded_case, db_session):
    """
    模板渲染不崩潰（不跑真實 WeasyPrint，只驗 HTML 輸出）。
    """
    from app.services.report_service import _fetch_report_data
    from jinja2 import Environment, FileSystemLoader
    from pathlib import Path

    data = await _fetch_report_data(
        case_id=seeded_case.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        requesting_user_id=seeded_case.parent_a_id,
        db=db_session,
    )

    template_dir = Path(__file__).parent.parent.parent / "app" / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    template = env.get_template("reports/monthly.html")
    html = template.render(**data)

    assert "共親職排程系統" in html
    assert data["case_name"] in html
    assert "免責聲明" in html


@pytest.mark.asyncio
async def test_pdf_generation(seeded_case, db_session, tmp_path, monkeypatch):
    """
    WeasyPrint 真實生成 PDF，驗 SHA-256 非空且檔案存在。
    （這個測試需要 WeasyPrint 安裝正確）
    """
    monkeypatch.setattr("app.services.report_service.settings",
                        MagicMock(PDF_STORAGE_MODE="local"))

    from app.services.report_service import generate_report
    report = await generate_report(
        case_id=seeded_case.id,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        report_type="custom_range",
        requesting_user_id=seeded_case.parent_a_id,
        db=db_session,
    )

    assert report.pdf_sha256
    assert len(report.pdf_sha256) == 64    # SHA-256 hex
    assert report.last_audit_id >= 0
    assert Path(report.pdf_gcs_path).exists()
```

### 8.2 Integration tests（`tests/integration/test_reports.py`）

```python
import pytest
from datetime import date
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_generate_and_download_report(client: AsyncClient, seeded_case, auth_headers):
    """完整流程：建規則 → 產 PDF → 下載 PDF。"""
    # 1. 產報告
    response = await client.post(
        f"/api/v1/cases/{seeded_case.id}/reports/",
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "report_type": "custom_range",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    report_data = response.json()
    assert report_data["pdf_sha256"]
    assert report_data["last_audit_hash"]

    # 2. 下載 PDF
    report_id = report_data["id"]
    dl_response = await client.get(
        f"/api/v1/cases/{seeded_case.id}/reports/{report_id}/download",
        headers=auth_headers,
    )
    assert dl_response.status_code == 200
    assert dl_response.headers["content-type"] == "application/pdf"
    assert len(dl_response.content) > 1000   # PDF 至少 1KB

    # 3. 驗 SHA-256 一致
    import hashlib
    assert hashlib.sha256(dl_response.content).hexdigest() == report_data["pdf_sha256"]


@pytest.mark.asyncio
async def test_report_audit_log_written(client: AsyncClient, seeded_case, auth_headers, db_session):
    """產報告後 audit_log 有 generate_report 紀錄。"""
    await client.post(
        f"/api/v1/cases/{seeded_case.id}/reports/",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31",
              "report_type": "custom_range"},
        headers=auth_headers,
    )
    from sqlalchemy import select
    from app.models.audit_log import AuditLog
    result = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "generate_report",
            AuditLog.case_id == seeded_case.id,
        )
    )
    logs = list(result.scalars().all())
    assert len(logs) >= 1
```

---

## 9. DoD（完成標準）

```bash
# 1. 重建 Docker image（因為改了 Dockerfile）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose build api"

# 2. 確認 WeasyPrint 安裝正確
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose run --rm api python -c \"import weasyprint; print('WeasyPrint', weasyprint.__version__)\""

# 3. Migration
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api alembic upgrade head"

# 4. 全部測試
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/unit tests/integration -v"
```

**驗證項目**：

**環境**
- [ ] `docker compose build api` 無錯（apt 安裝 WeasyPrint 依賴成功）
- [ ] `import weasyprint` 無錯，版本 ≥ 62.0
- [ ] `fonts-noto-cjk` 已安裝（`fc-list | grep Noto` 有輸出）

**功能**
- [ ] `POST /cases/{id}/reports/` 回傳 201，`pdf_sha256` 非空
- [ ] `GET /cases/{id}/reports/{id}/download` 回傳 `application/pdf`，檔案 > 1KB
- [ ] 下載的 PDF 用 PDF viewer 打開，中文顯示正常（無亂碼）
- [ ] 封面有「稽核完整性」區塊，`last_audit_hash` 與 DB 一致
- [ ] 產報告後 `audit_log` 有 `generate_report` 紀錄

**測試**
- [ ] `test_html_render_no_crash` 通過
- [ ] `test_pdf_generation` 通過（WeasyPrint 真實跑）
- [ ] `test_generate_and_download_report` 通過
- [ ] SHA-256 驗證一致
- [ ] M1.3–M1.5 所有 evals 仍全綠（無回歸）

---

## 10. 給 Claude Code 的注意事項

1. **Dockerfile 改了要重 build**：`docker compose up -d` 不會自動 rebuild。改完 Dockerfile 後必須先 `docker compose build api` 再 `docker compose up -d`。

2. **字型路徑**：`fonts-noto-cjk` 在 Debian slim 安裝後，字型通常在 `/usr/share/fonts/opentype/noto/`。若 WeasyPrint 找不到字型，用 `fc-list` 確認實際路徑後更新 `base.html` 的 `@font-face src`。

3. **WeasyPrint 的 `HTML(string=...)` 是同步的**：不要 `await`，直接呼叫，`write_pdf()` 也是同步。若要防止 block event loop，用 `run_in_executor` 包住（PDF 生成通常 1–3 秒）。

4. **`reports` 表的 `pdf_gcs_path` 不能為空字串**：local 模式要確認路徑真的有值（`/tmp/reports/...`），GCS 模式確認 bucket path（`gs://...`）。

5. **`_fetch_report_data` 裡的時區邊界**：`period_end` 用 `dt.max.time()`（23:59:59.999...），確保當天最後的事件不被漏掉。

6. **`reports` ORM model** 需自行建立 `app/models/report.py`，欄位與 Migration 013 一致。`anchor_id` 是 nullable FK。
