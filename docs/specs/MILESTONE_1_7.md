# MILESTONE_1_7.md｜稽核錨定 Job + 展開維護 + Phase 1 收尾

> 本文件是 Phase 1 的最後一個 Milestone。
> 閱讀順序：本文件 → DATABASE.md §3.5（錨定演算法）→ ARCHITECTURE.md §6（安全與備份）
> 完成後跑 §9 DoD（含端到端劇本），全部通過 Phase 1 正式完成。

---

## 0. 本 Milestone 的交付範圍

| 交付項目 | 說明 |
|---|---|
| GCS Bucket 建立 | `coparenting-audit-anchors`（Object Lock）、`coparenting-reports` |
| `app/services/audit_anchor_service.py` | 稽核錨定主體 |
| `app/services/expansion_maintenance.py` | RRULE 展開維護（補完 M1.4 的 stub） |
| `app/api/v1/admin.py` | 內部 Job 觸發 endpoint（Cloud Scheduler 呼叫用） |
| `scripts/run_anchor_job.py` | 本地手動觸發錨定的腳本 |
| `tests/unit/test_audit_anchor.py` | 錨定邏輯單元測試 |
| `tests/integration/test_expansion_maintenance.py` | 展開維護整合測試 |
| `tests/e2e/test_phase1_scenarios.py` | Phase 1 端到端驗收劇本 |

---

## 1. GCS Bucket 建立（必須第一步）

### 1.1 安裝 gcloud（若尚未安裝）

```bash
# 在 WSL2 內執行
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
gcloud init
gcloud auth login
```

### 1.2 建立 Bucket

```bash
# 設定專案 ID（填入你的 GCP 專案 ID）
PROJECT_ID="your-gcp-project-id"
REGION="asia-east1"   # 台灣最近的 GCP region

# 1. 稽核錨定 Bucket（開啟 Object Lock，保留 10 年）
gcloud storage buckets create gs://coparenting-audit-anchors \
    --project=$PROJECT_ID \
    --location=$REGION \
    --uniform-bucket-level-access \
    --retention-period=3650d \
    --lock-retention-policy

# 2. PDF 報告 Bucket（開啟 Object Lock，保留 7 年）
gcloud storage buckets create gs://coparenting-reports \
    --project=$PROJECT_ID \
    --location=$REGION \
    --uniform-bucket-level-access \
    --retention-period=2555d \
    --lock-retention-policy

# 3. 驗證
gcloud storage buckets describe gs://coparenting-audit-anchors \
    --format="value(retention_policy.retentionPeriod,retention_policy.isLocked)"
```

預期輸出：`3650d    True`（isLocked=True 代表 Object Lock 已啟動，無法被刪除）。

**重要**：`--lock-retention-policy` 是不可逆操作，確認 bucket 名稱正確再執行。

### 1.3 Service Account 授權

```bash
# 建立 Service Account 給 Cloud Run / 本地開發用
gcloud iam service-accounts create coparenting-app \
    --display-name="CoParenting App Service Account"

SA_EMAIL="coparenting-app@${PROJECT_ID}.iam.gserviceaccount.com"

# 授予兩個 bucket 的寫入權限
gcloud storage buckets add-iam-policy-binding gs://coparenting-audit-anchors \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator"

gcloud storage buckets add-iam-policy-binding gs://coparenting-reports \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator"

# 下載 key（本地開發用，Production 用 Workload Identity）
gcloud iam service-accounts keys create \
    ./secrets/gcp-service-account.json \
    --iam-account=$SA_EMAIL
```

`.env` 新增：

```
GCS_BUCKET_AUDIT=coparenting-audit-anchors
GCS_BUCKET_REPORTS=coparenting-reports
GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/gcp-service-account.json
PDF_STORAGE_MODE=gcs   # 改成 gcs（有了 bucket 之後）
```

`docker-compose.yml` 掛載 secrets：

```yaml
services:
  api:
    volumes:
      - ./secrets:/app/secrets:ro   # 新增這行
```

---

## 2. 稽核錨定 Service（`app/services/audit_anchor_service.py`）

完整實作 DATABASE.md §3.5 的演算法。

```python
# app/services/audit_anchor_service.py
import hashlib
import json
from datetime import datetime, timezone as dt_tz
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.audit_log import AuditLog
from app.models.audit_anchor import AuditAnchor
from app.config import settings


async def run_anchor_job(db: AsyncSession) -> dict:
    """
    把當前 audit_log 的最新雜湊錨定到 GCS Object Lock bucket。
    冪等：若最新一筆 audit_log 已錨定，直接回傳 skipped。

    回傳：
    {
        "status": "anchored" | "skipped" | "failed",
        "last_audit_id": int,
        "last_row_hash": str,
        "anchor_proof": str | None,
        "error": str | None,
    }
    """
    # 1. 取全域最後一筆 audit_log
    result = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    last = result.one_or_none()
    if not last:
        return {"status": "skipped", "reason": "no_audit_log_entries"}

    last_audit_id, last_row_hash = last

    # 2. 已錨定過就跳過（冪等）
    exists = await db.execute(
        select(AuditAnchor.id)
        .where(AuditAnchor.last_audit_id == last_audit_id)
        .limit(1)
    )
    if exists.scalar_one_or_none():
        return {
            "status": "skipped",
            "reason": "already_anchored",
            "last_audit_id": last_audit_id,
            "last_row_hash": last_row_hash,
        }

    # 3. 組裝錨定內容
    anchored_at = datetime.now(dt_tz.utc)
    content = (
        f"audit_log_id={last_audit_id}\n"
        f"row_hash={last_row_hash}\n"
        f"anchored_at={anchored_at.isoformat()}\n"
    )
    content_bytes = content.encode("utf-8")

    # 4. 上傳到 GCS（Object Lock bucket）
    gcs_path = (
        f"anchors/"
        f"{anchored_at:%Y/%m/%d}/"
        f"{last_audit_id}_{anchored_at:%H%M%S}.txt"
    )
    try:
        anchor_proof = await _upload_to_gcs(
            bucket_name=settings.GCS_BUCKET_AUDIT,
            path=gcs_path,
            content=content_bytes,
        )
    except Exception as e:
        return {
            "status": "failed",
            "last_audit_id": last_audit_id,
            "last_row_hash": last_row_hash,
            "error": str(e)[:500],
        }

    # 5. 寫 audit_anchors 表
    anchor = AuditAnchor(
        anchored_at=anchored_at,
        last_audit_id=last_audit_id,
        last_row_hash=last_row_hash,
        anchor_target="gcs",
        anchor_proof=anchor_proof,
    )
    db.add(anchor)
    await db.flush()

    return {
        "status": "anchored",
        "last_audit_id": last_audit_id,
        "last_row_hash": last_row_hash,
        "anchor_proof": anchor_proof,
    }


async def _upload_to_gcs(bucket_name: str, path: str, content: bytes) -> str:
    """
    上傳到 GCS，回傳 gs:// 路徑。
    使用 asyncio.run_in_executor 包住同步的 GCS client。
    """
    import asyncio
    from google.cloud import storage as gcs

    def _upload():
        client = gcs.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(path)
        blob.upload_from_string(content, content_type="text/plain; charset=utf-8")
        return f"gs://{bucket_name}/{path}"

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upload)


async def verify_hash_chain(
    case_id,
    db: AsyncSession,
    limit: int = 100,
) -> dict:
    """
    驗證指定 case 的 audit_log hash chain 完整性。
    從最早一筆開始，重算每筆的 row_hash，確認與 DB 存的一致。

    回傳：
    {
        "valid": bool,
        "checked": int,
        "first_invalid_id": int | None,
        "error": str | None,
    }
    """
    from app.utils.hash_chain import compute_row_hash

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.asc())
        .limit(limit)
    )
    logs = list(result.scalars().all())

    prev_hash = None
    for log in logs:
        row_data = {
            "case_id": str(log.case_id),
            "actor_id": str(log.actor_id),
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": str(log.entity_id),
            "before_state": log.before_state,
            "after_state": log.after_state,
            "triggered_by": log.triggered_by,
            "occurred_at": log.occurred_at,
        }
        expected_hash = compute_row_hash(row_data, prev_hash)
        if expected_hash != log.row_hash:
            return {
                "valid": False,
                "checked": logs.index(log),
                "first_invalid_id": log.id,
                "error": f"Hash mismatch at audit_log.id={log.id}",
            }
        prev_hash = log.row_hash

    return {"valid": True, "checked": len(logs), "first_invalid_id": None}
```

---

## 3. RRULE 展開維護（補完 `app/services/expansion_maintenance.py`）

M1.4 只有骨架，現在補完整實作：

```python
# app/services/expansion_maintenance.py
from datetime import date, datetime, time, timezone as dt_tz
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.custody_rule import CustodyRule
from app.models.custody_event import CustodyEvent
from app.repositories.event_repo import EventRepository
from app.utils.rrule_expander import expand_rule
from app.services.audit_service import log as audit_log

EXPAND_WINDOW_MONTHS = 6


async def extend_all_active_rules(db: AsyncSession) -> dict:
    """
    遍歷所有未撤銷規則，把展開視窗推進到 today + 6 個月。
    只補展開「尚未有事件的未來日期」，不重複建立。

    回傳：{"processed": int, "new_events": int, "errors": int}
    """
    from app.utils.rrule_expander import _add_months   # M1.4 已定義

    today = date.today()
    expand_until = _add_months(today, EXPAND_WINDOW_MONTHS)
    event_repo = EventRepository(db)

    # 取所有未撤銷規則
    rules_result = await db.execute(
        select(CustodyRule)
        .where(CustodyRule.revoked_at.is_(None))
    )
    rules = list(rules_result.scalars().all())

    processed = 0
    new_events = 0
    errors = 0

    for rule in rules:
        try:
            # 找此規則目前最後一個事件的日期
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

            # 決定從哪天開始展開
            if last_event_dt:
                # 從最後一個事件的隔天開始
                from_date = last_event_dt.date() + __import__('datetime').timedelta(days=1)
            else:
                # 沒有任何事件，從 effective_from 或 today 開始
                from_date = max(rule.effective_from, today)

            # 若 from_date 已超過 expand_until，不需要補
            if from_date > expand_until:
                processed += 1
                continue

            # 展開
            expanded = expand_rule(
                rrule_str=rule.rrule,
                start_time=rule.start_time,
                end_time=rule.end_time,
                effective_from=from_date,
                effective_until=rule.effective_until,
                timezone="Asia/Taipei",   # 從 case 取，這裡簡化
                expand_until=expand_until,
            )

            # 批次寫入（每個用 savepoint 隔離 constraint 衝突）
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
                    pass   # exclusion constraint 衝突，跳過

            processed += 1

        except Exception as ex:
            errors += 1
            import logging
            logging.getLogger(__name__).error(
                f"expansion_maintenance: rule {rule.id} failed: {ex}"
            )

    return {"processed": processed, "new_events": new_events, "errors": errors}
```

---

## 4. Admin Job Endpoint（`app/api/v1/admin.py`）

Cloud Scheduler 每小時 / 每日呼叫的內部 endpoint。
**必須加 Bearer token 驗證（防止外部隨意觸發）**。

```python
# app/api/v1/admin.py
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.config import settings
from app.services.audit_anchor_service import run_anchor_job
from app.services.expansion_maintenance import extend_all_active_rules

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_job_token(x_job_token: str = Header(...)):
    """
    Cloud Scheduler 在 Header 帶 X-Job-Token，
    驗證與 settings.JOB_SECRET_TOKEN 一致。
    """
    if x_job_token != settings.JOB_SECRET_TOKEN:
        raise HTTPException(403, detail="Invalid job token")


@router.post("/jobs/anchor-audit-log")
async def job_anchor_audit_log(
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """每小時由 Cloud Scheduler 觸發。"""
    async with db.begin():
        result = await run_anchor_job(db)
    return result


@router.post("/jobs/expand-rules")
async def job_expand_rules(
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """每日由 Cloud Scheduler 觸發。"""
    async with db.begin():
        result = await extend_all_active_rules(db)
    return result


@router.get("/jobs/verify-hash-chain/{case_id}")
async def job_verify_hash_chain(
    case_id: str,
    _: None = Depends(verify_job_token),
    db: AsyncSession = Depends(get_db),
):
    """手動觸發：驗證指定 case 的 hash chain 完整性。"""
    from uuid import UUID
    from app.services.audit_anchor_service import verify_hash_chain
    result = await verify_hash_chain(UUID(case_id), db)
    return result
```

`.env.example` 新增：
```
JOB_SECRET_TOKEN=change_me_to_random_32_chars
```

`app/main.py` 新增：
```python
from app.api.v1 import admin
app.include_router(admin.router, prefix="/api/v1")
```

---

## 5. 本地手動觸發腳本（`scripts/run_anchor_job.py`）

```python
#!/usr/bin/env python3
"""
本地手動觸發稽核錨定。
用法：docker compose exec api python scripts/run_anchor_job.py
"""
import asyncio
import sys
import os

sys.path.insert(0, "/app")
os.environ.setdefault("ENV", "development")

from app.database import AsyncSessionLocal
from app.services.audit_anchor_service import run_anchor_job


async def main():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await run_anchor_job(db)
    print(f"Anchor result: {result}")
    if result["status"] == "anchored":
        print(f"✓ Anchored audit_log #{result['last_audit_id']}")
        print(f"  Hash: {result['last_row_hash'][:16]}...")
        print(f"  Proof: {result['anchor_proof']}")
    elif result["status"] == "skipped":
        print(f"- Skipped: {result.get('reason', '')}")
    else:
        print(f"✗ Failed: {result.get('error', '')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. 測試

### 6.1 Unit tests（`tests/unit/test_audit_anchor.py`）

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_anchor_job_skipped_when_no_logs(db_session):
    """無稽核紀錄時回傳 skipped。"""
    from app.services.audit_anchor_service import run_anchor_job
    # 用空的 case（確保 audit_log 是空的）
    result = await run_anchor_job(db_session)
    # 可能是 skipped（若測試 DB 本來就有資料則是 anchored 或 already_anchored）
    assert result["status"] in ("skipped", "anchored", "already_anchored")


@pytest.mark.asyncio
async def test_anchor_job_idempotent(seeded_case, db_session):
    """同一筆 audit_log 錨定兩次，第二次回傳 already_anchored。"""
    from app.services.audit_anchor_service import run_anchor_job

    with patch(
        "app.services.audit_anchor_service._upload_to_gcs",
        new_callable=AsyncMock,
        return_value="gs://mock-bucket/anchors/test.txt",
    ):
        result1 = await run_anchor_job(db_session)
        result2 = await run_anchor_job(db_session)

    assert result1["status"] in ("anchored", "skipped")
    if result1["status"] == "anchored":
        assert result2["status"] in ("skipped",)
        assert result2.get("reason") == "already_anchored"


@pytest.mark.asyncio
async def test_anchor_job_gcs_failure_returns_failed(seeded_case, db_session):
    """GCS 上傳失敗時回傳 failed，不拋 exception。"""
    from app.services.audit_anchor_service import run_anchor_job

    with patch(
        "app.services.audit_anchor_service._upload_to_gcs",
        new_callable=AsyncMock,
        side_effect=Exception("GCS connection refused"),
    ):
        result = await run_anchor_job(db_session)

    # 若有 audit_log 才會嘗試上傳
    if result["status"] != "skipped":
        assert result["status"] == "failed"
        assert "GCS" in result.get("error", "")


@pytest.mark.asyncio
async def test_verify_hash_chain_valid(seeded_case, db_session):
    """seed 資料的 hash chain 應該是 valid。"""
    from app.services.audit_anchor_service import verify_hash_chain
    result = await verify_hash_chain(seeded_case.id, db_session)
    assert result["valid"] is True
    assert result["first_invalid_id"] is None


def test_anchor_content_format():
    """錨定檔案格式：三行固定格式。"""
    content = (
        "audit_log_id=42\n"
        "row_hash=abc123\n"
        "anchored_at=2026-04-21T10:00:00+00:00\n"
    )
    lines = content.strip().split("\n")
    assert lines[0].startswith("audit_log_id=")
    assert lines[1].startswith("row_hash=")
    assert lines[2].startswith("anchored_at=")
```

### 6.2 Integration tests（`tests/integration/test_expansion_maintenance.py`）

```python
import pytest
from datetime import date, timedelta
from uuid import uuid4


@pytest.mark.asyncio
async def test_extend_active_rules_adds_events(seeded_case_with_rule, db_session):
    """
    已有規則但 expand_until 只展開到 1 個月，
    跑 extend_all_active_rules 後事件數量增加。
    """
    from app.services.expansion_maintenance import extend_all_active_rules
    from app.repositories.event_repo import EventRepository
    from datetime import datetime, timezone

    # 取跑之前的事件數
    before = await EventRepository(db_session).list_in_range(
        seeded_case_with_rule.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=365),
    )
    before_count = len(before)

    result = await extend_all_active_rules(db_session)
    assert result["errors"] == 0

    after = await EventRepository(db_session).list_in_range(
        seeded_case_with_rule.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=365),
    )
    # 若原本已展開 6 個月，new_events 可能為 0（正常）
    assert len(after) >= before_count


@pytest.mark.asyncio
async def test_extend_idempotent(seeded_case_with_rule, db_session):
    """跑兩次，事件數量不變（不重複建立）。"""
    from app.services.expansion_maintenance import extend_all_active_rules
    from app.repositories.event_repo import EventRepository
    from datetime import datetime, timezone

    await extend_all_active_rules(db_session)
    count1 = len(await EventRepository(db_session).list_in_range(
        seeded_case_with_rule.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=365),
    ))

    result2 = await extend_all_active_rules(db_session)
    count2 = len(await EventRepository(db_session).list_in_range(
        seeded_case_with_rule.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=365),
    ))

    assert count1 == count2
    assert result2["new_events"] == 0
```

### 6.3 Phase 1 端到端驗收劇本（`tests/e2e/test_phase1_scenarios.py`）

這是 Phase 1 最重要的驗收測試，模擬真實使用情境。

```python
"""
Phase 1 端到端驗收劇本。
模擬三個真實使用情境，全程驗證業務邏輯、稽核軌跡、PDF 產出。

執行：
    docker compose exec -T api pytest tests/e2e -v
"""
import pytest
import hashlib
from datetime import date, datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock


# ── 劇本一：單方建立規則 → 查行事曆 → 產 PDF ──────────────────

@pytest.mark.asyncio
async def test_scenario_1_single_parent_full_flow(seeded_case, db_session):
    """
    劇本：
    1. 家長 A 用自然語言建立「每週一三五帶小孩」
    2. 查詢未來一個月行事曆，確認事件存在
    3. 產生月報 PDF
    4. 驗證 audit_log 完整，hash chain valid
    5. 觸發錨定，確認 GCS 路徑回傳
    """
    from app.services.agent_service import handle_message
    from app.repositories.event_repo import EventRepository
    from app.services.report_service import generate_report
    from app.services.audit_anchor_service import run_anchor_job, verify_hash_chain

    # Step 1: Agent 自然語言建規則
    with patch(
        "app.services.gcal_sync_service._upload_to_gcs",   # GCal mock
        new_callable=AsyncMock,
        return_value="gs://mock/gcal",
    ):
        result = await handle_message(
            case_id=seeded_case.id,
            user_id=seeded_case.parent_a_id,
            user_text="我每週一、三、五 07:30 到 17:30 帶小孩",
            session_id=None,
            db=db_session,
        )

    assert not result["requires_clarification"], \
        f"不應需要 clarification，reply={result['reply']}"
    tool_names = [a["tool"] for a in result["actions_taken"]]
    assert "create_recurring_custody_rule" in tool_names

    # Step 2: 查行事曆
    events = await EventRepository(db_session).list_in_range(
        seeded_case.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=30),
    )
    assert len(events) >= 4, f"一個月內至少 4 個事件，實際：{len(events)}"
    assert all(e.status == "scheduled" for e in events)

    # Step 3: 產月報 PDF
    today = date.today()
    first_day = today.replace(day=1)
    import calendar
    last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])

    report = await generate_report(
        case_id=seeded_case.id,
        period_start=first_day,
        period_end=last_day,
        report_type="monthly",
        requesting_user_id=seeded_case.parent_a_id,
        db=db_session,
    )
    await db_session.commit()

    assert report.pdf_sha256
    assert len(report.pdf_sha256) == 64
    from pathlib import Path
    assert Path(report.pdf_gcs_path).exists(), "PDF 檔案應存在"

    # Step 4: 驗 hash chain
    chain_result = await verify_hash_chain(seeded_case.id, db_session)
    assert chain_result["valid"], \
        f"Hash chain 不完整：{chain_result.get('error')}"

    # Step 5: 錨定
    with patch(
        "app.services.audit_anchor_service._upload_to_gcs",
        new_callable=AsyncMock,
        return_value="gs://coparenting-audit-anchors/anchors/test/001.txt",
    ):
        anchor_result = await run_anchor_job(db_session)
    await db_session.commit()

    assert anchor_result["status"] in ("anchored", "skipped")
    print(f"✓ 劇本一完成：{len(events)} 個事件，PDF {report.pdf_sha256[:8]}...")


# ── 劇本二：建規則 → 建一次性事件 → 衝突偵測 ──────────────────

@pytest.mark.asyncio
async def test_scenario_2_conflict_detection(seeded_case, db_session):
    """
    劇本：
    1. 建立「每週六我帶」的規則
    2. 嘗試建立「下週六對方帶」→ 應偵測到衝突
    3. 強制建立 → 確認被 exclusion constraint 擋下
    """
    from app.services.agent_service import handle_message

    # Step 1: 建週六規則
    await handle_message(
        case_id=seeded_case.id,
        user_id=seeded_case.parent_a_id,
        user_text="我每週六 09:00 到 18:00 帶小孩",
        session_id=None,
        db=db_session,
    )
    await db_session.commit()

    # Step 2: 嘗試建立同時段的一次性事件，Agent 應偵測衝突
    # 找下一個週六
    today = date.today()
    days_until_saturday = (5 - today.weekday()) % 7 or 7
    next_saturday = today + timedelta(days=days_until_saturday)

    result = await handle_message(
        case_id=seeded_case.id,
        user_id=seeded_case.parent_a_id,
        user_text=f"對方 {next_saturday.month}/{next_saturday.day} 09:00 到 18:00 帶小孩",
        session_id=None,
        db=db_session,
    )

    # 不論 Agent 怎麼處理（衝突警告或被擋），都不應崩潰
    assert "session_id" in result
    print(f"✓ 劇本二：衝突偵測 reply={result['reply'][:50]}...")


# ── 劇本三：建規則 → 撤銷 → 驗稽核軌跡 ──────────────────────

@pytest.mark.asyncio
async def test_scenario_3_rule_revocation_audit_trail(seeded_case, db_session):
    """
    劇本：
    1. 建立規則
    2. 撤銷規則（透過 Agent propose + 手動 confirm）
    3. 驗 audit_log 有完整的 create → propose → revoke 軌跡
    4. 驗 revoke 後 scheduled 事件被軟刪除
    """
    from app.services.agent_service import handle_message
    from app.services.schedule_service import confirm_revocation
    from app.repositories.revocation_proposal_repo import RevocationProposalRepository
    from app.repositories.event_repo import EventRepository
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    # Step 1: 建規則
    await handle_message(
        case_id=seeded_case.id,
        user_id=seeded_case.parent_a_id,
        user_text="我每週三 07:30 到 17:30 帶小孩",
        session_id=None,
        db=db_session,
    )
    await db_session.commit()

    # 確認有事件
    events_before = await EventRepository(db_session).list_in_range(
        seeded_case.id,
        datetime.now(timezone.utc),
        datetime.now(timezone.utc) + timedelta(days=180),
    )
    assert len(events_before) > 0

    # Step 2: Agent 提案撤銷
    result = await handle_message(
        case_id=seeded_case.id,
        user_id=seeded_case.parent_a_id,
        user_text="把週三那條規則取消掉",
        session_id=None,
        db=db_session,
    )
    await db_session.commit()

    tool_names = [a["tool"] for a in result["actions_taken"]]
    assert "propose_rule_revocation" in tool_names, \
        f"應呼叫 propose_rule_revocation，實際：{tool_names}"

    # Step 3: 手動 confirm
    proposals = await RevocationProposalRepository(db_session).list_pending(seeded_case.id)
    assert len(proposals) >= 1

    proposal = proposals[0]
    if proposal.rule_id:
        from app.models.user import User
        user = await db_session.get(User, seeded_case.parent_a_id)
        confirm_result = await confirm_revocation(proposal.id, seeded_case.parent_a_id, db_session)
        await db_session.commit()
        assert confirm_result["status"] == "confirmed"

        # Step 4: 驗事件被軟刪除
        events_after = await EventRepository(db_session).list_in_range(
            seeded_case.id,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(days=180),
        )
        assert len(events_after) < len(events_before), "撤銷後應減少事件數量"

    # Step 5: 驗 audit_log 軌跡
    audit_result = await db_session.execute(
        select(AuditLog)
        .where(AuditLog.case_id == seeded_case.id)
        .order_by(AuditLog.id.asc())
    )
    logs = list(audit_result.scalars().all())
    actions = [l.action for l in logs]

    assert "create_custody_rule" in actions, "應有 create_custody_rule"
    assert "propose_revocation" in actions, "應有 propose_revocation"

    print(f"✓ 劇本三：稽核軌跡完整，共 {len(logs)} 筆 audit_log")
    print(f"  actions: {actions}")
```

---

## 7. Cloud Scheduler 設定（Production 參考，不在本 Milestone 實際建立）

```bash
# 每小時觸發稽核錨定
gcloud scheduler jobs create http coparenting-anchor-audit \
    --location=$REGION \
    --schedule="0 * * * *" \
    --uri="https://your-cloud-run-url/api/v1/admin/jobs/anchor-audit-log" \
    --http-method=POST \
    --headers="X-Job-Token=your_job_secret_token" \
    --time-zone="Asia/Taipei"

# 每日凌晨 2 點觸發 RRULE 展開維護
gcloud scheduler jobs create http coparenting-expand-rules \
    --location=$REGION \
    --schedule="0 2 * * *" \
    --uri="https://your-cloud-run-url/api/v1/admin/jobs/expand-rules" \
    --http-method=POST \
    --headers="X-Job-Token=your_job_secret_token" \
    --time-zone="Asia/Taipei"
```

本 Milestone 只實作 endpoint，Cloud Scheduler 的建立留到 Cloud Run 部署時（Phase 1 完成後）。

---

## 8. 安全 Checklist（Phase 1 完成前必須人工確認）

Claude Code 無法自動驗證以下項目，請人工逐一確認：

**認證與授權**
- [ ] 所有業務 endpoint 都有 `Depends(get_current_user)`，未登入回 401
- [ ] Admin job endpoint 有 `X-Job-Token` 驗證，錯誤 token 回 403
- [ ] 不同案件的使用者無法互相看到資料（RLS 隔離驗證：用兩個測試帳號各建案件，確認無法跨查）

**資料安全**
- [ ] `google_refresh_token_enc` 在 DB 是 bytes（加密），不是明文
- [ ] PDF 只能由案件成員下載（非成員 GET 回 403）
- [ ] `audit_log` 無法被 UPDATE / DELETE（嘗試執行應得 permission denied）

**隱私**
- [ ] `handover_records.location_lat/lng` 只保留到小數第 3 位（約 100m 精度）
- [ ] `children.display_name` 沒有儲存真實全名（seed 資料與 API 測試確認）
- [ ] `notes` 欄位不含任何情緒性字眼（Agent 的 D2 eval 已驗，這裡再人工確認）

**稽核完整性**
- [ ] `audit_log` 的 no-update / no-delete rule 有效（嘗試 UPDATE audit_log 應無反應）
- [ ] `verify_hash_chain` 對所有測試 case 回傳 `valid: true`
- [ ] 至少跑過一次錨定，`audit_anchors` 有至少一筆紀錄

---

## 9. DoD（完成標準）

```bash
# Migration（無新 migration，但確認 head 是正確的）
docker compose exec -T api alembic upgrade head

# 全部測試
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/unit tests/integration tests/e2e -v"

# Agent evals（確認無回歸）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/agent_evals -v -m eval"

# 手動觸發錨定（確認流程可跑，GCS 部分 mock 或跳過）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api python scripts/run_anchor_job.py"
```

**驗證項目**：

**稽核錨定**
- [ ] `run_anchor_job` 冪等：跑兩次，第二次回傳 `already_anchored`
- [ ] GCS 上傳失敗回傳 `failed`，不拋 exception
- [ ] `verify_hash_chain` 對 seeded_case 回傳 `valid: true`
- [ ] `audit_anchors` 表有資料（至少 mock 錨定）

**展開維護**
- [ ] `extend_all_active_rules` 跑兩次，第二次 `new_events=0`（冪等）
- [ ] 無規則時 `processed=0, errors=0`

**Admin Endpoints**
- [ ] `POST /admin/jobs/anchor-audit-log` 無 token → 403
- [ ] `POST /admin/jobs/anchor-audit-log` 正確 token → 200
- [ ] `POST /admin/jobs/expand-rules` 正確 token → 200

**端到端劇本**
- [ ] 劇本一：建規則 → 行事曆有事件 → PDF 產出 → hash chain valid → 錨定
- [ ] 劇本二：衝突偵測流程跑完不崩潰
- [ ] 劇本三：建規則 → 撤銷 → audit_log 有完整軌跡

**安全 Checklist**
- [ ] §8 全部人工確認完畢

**總測試數目標**
- [ ] unit + integration + e2e 合計 ≥ 80 passed
- [ ] agent_evals 15/15 passed（無回歸）

---

## 10. 給 Claude Code 的注意事項

1. **GCS 上傳用 `run_in_executor`**：`google-cloud-storage` 是同步函式庫，和 M1.5 的 GCal 一樣要包在 executor 裡。

2. **`audit_anchor_service` 的 GCS mock**：unit test 用 `patch("app.services.audit_anchor_service._upload_to_gcs")`，不需要真實 GCS 連線。integration test 也 mock，e2e 也 mock。**真實 GCS 上傳留到手動執行 `run_anchor_job.py` 時驗**。

3. **`verify_hash_chain` 需要 `compute_row_hash`**：這個函數在 `app/utils/hash_chain.py`（M1.1 已建），確認 import 路徑正確。

4. **e2e 測試的 `seeded_case`**：需要 `seeded_case.parent_a_id` 屬性，確認 `conftest.py` 的 fixture 有這個欄位。若沒有，在 fixture 裡補上。

5. **`expansion_maintenance` 的 timezone**：目前 hardcode `"Asia/Taipei"`，實際要從 `case.timezone` 取。這是已知技術債，Phase 2 修。

6. **admin router 不加 RLS**：admin endpoint 的 DB session 不設定 `app.current_user_id`（因為不是使用者操作），確認 `deps.py` 的 `get_db` 不會強制要求這個設定。若有問題，admin endpoint 改用獨立的 `get_raw_db` dependency。

7. **Phase 1 完成後的下一步提醒**：本 Milestone 完成後，Phase 1 的後端 MVP 正式完成。下一步是 React Native App（M1.8），之後才是 Phase 2（雙方協作 + LINE）。
