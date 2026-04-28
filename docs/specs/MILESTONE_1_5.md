# MILESTONE_1_5.md｜Google Calendar 同步

> 閱讀順序：本文件 → ARCHITECTURE.md §5.1 → DATABASE.md（custody_events.gcal_event_id）
> 完成後跑 §8 DoD，全部通過才算完成。

---

## 0. 前置狀態確認

在動手前確認以下事項，若未完成先處理再實作：

```bash
# 確認 .env 有這些值（不能是空字串）
docker compose exec -T api python -c "
from app.config import settings
print('CLIENT_ID:', settings.GOOGLE_OAUTH_CLIENT_ID[:10] if settings.GOOGLE_OAUTH_CLIENT_ID else 'MISSING')
print('CLIENT_SECRET:', 'OK' if settings.GOOGLE_OAUTH_CLIENT_SECRET else 'MISSING')
print('REDIRECT_URI:', settings.GOOGLE_OAUTH_REDIRECT_URI)
"
```

若 CLIENT_ID / CLIENT_SECRET 是 MISSING，先在 GCP Console 完成以下設定：
1. APIs & Services → OAuth 2.0 Client IDs → Create（Web application）
2. Authorized redirect URIs 加入 `http://localhost:8000/api/v1/auth/google/callback`
3. 啟用 Google Calendar API
4. 填入 `.env`

---

## 1. 本 Milestone 的交付範圍

| 交付項目 | 說明 |
|---|---|
| `app/services/integrations/google_calendar.py` | GCal API 封裝（可 mock） |
| `app/services/gcal_sync_service.py` | 同步邏輯主體 |
| Migration 012 | `gcal_sync_log` 表 |
| `app/api/v1/schedules.py` 更新 | 建立事件後觸發 GCal 同步 |
| `tests/unit/test_gcal_sync.py` | mock 測試（不需真實 token） |
| `tests/integration/test_gcal_live.py` | 端到端測試（需真實 token，標記 `gcal_live`） |

---

## 2. 架構決策：同步 vs 非同步

### MVP 選擇：同步呼叫

規則或事件建立後，**在同一個 API request 內**呼叫 GCal API。

優點：簡單、不用架 Pub/Sub。  
缺點：GCal API 若慢或失敗，會拖慢 response。

**緩解策略**：
- GCal 呼叫設 5 秒 timeout
- 失敗不影響主流程（業務資料已落庫），只記錄在 `gcal_sync_log`
- 前端顯示「已儲存，GCal 同步中...」，不需等 GCal 回應

### 未來遷移路徑（不在本 Milestone 實作）

```
現在：schedule_service.create_rule() → gcal_sync_service.sync_rule(rule)
未來：schedule_service.create_rule() → publish("gcal.sync", rule_id)
                                          ↓
                                   Cloud Run Worker → gcal_sync_service.sync_rule(rule)
```

介面保持一致，未來只需在 `schedule_service` 改觸發方式，不改 `gcal_sync_service`。

---

## 3. Migration 012（`gcal_sync_log`）

`alembic/versions/012_gcal_sync_log.py`：

```python
"""012: gcal sync log

Revision ID: 012
Revises: 011
"""
from alembic import op

def upgrade():
    op.execute("""
        CREATE TABLE gcal_sync_log (
            id          BIGSERIAL PRIMARY KEY,
            entity_type TEXT NOT NULL
                        CHECK (entity_type IN ('custody_event', 'custody_rule')),
            entity_id   UUID NOT NULL,
            user_id     UUID NOT NULL REFERENCES users(id),
            action      TEXT NOT NULL
                        CHECK (action IN ('insert', 'update', 'delete')),
            status      TEXT NOT NULL
                        CHECK (status IN ('success', 'failed', 'skipped')),
            gcal_event_id TEXT,
            error_message TEXT,
            duration_ms INT,
            synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_gcal_sync_entity
            ON gcal_sync_log(entity_type, entity_id, synced_at DESC);
        CREATE INDEX idx_gcal_sync_failed
            ON gcal_sync_log(status, synced_at DESC)
            WHERE status = 'failed';
    """)

    # 注意：gcal_sync_log 不開 RLS（沒有 case_id），
    -- 由 app_role 層控制，service 層只查自己觸發的紀錄

def downgrade():
    op.execute("DROP TABLE IF EXISTS gcal_sync_log;")
```

---

## 4. Google Calendar Client（`app/services/integrations/google_calendar.py`）

這是唯一直接呼叫 Google API 的地方，設計成可注入 mock。

### 4.1 資料結構

```python
# app/services/integrations/google_calendar.py
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class GCalEventInput:
    """建立 GCal 事件的輸入。"""
    summary: str              # 事件標題，例如「[共親職] 小寶 - 我監護」
    starts_at: datetime       # aware datetime
    ends_at: datetime         # aware datetime
    description: str = ""     # 事件描述（放 app 連結、備註）
    location: str = ""        # 交接地點
    color_id: str = "1"       # Google Calendar 顏色 ID（1=藍、2=綠...）


@dataclass
class GCalEventResult:
    gcal_event_id: str
    gcal_html_link: str
    gcal_updated: str         # ISO 8601


class GCalClientProtocol(Protocol):
    """
    介面定義。讓 mock 和真實 client 可以互換。
    任何實作這個 Protocol 的 class 都可以傳入 gcal_sync_service。
    """
    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult: ...

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult: ...

    async def delete_event(
        self, calendar_id: str, gcal_event_id: str
    ) -> None: ...
```

### 4.2 真實實作

```python
import asyncio
import httpx
from datetime import timezone as dt_tz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.utils.kms import decrypt


class GoogleCalendarClient:
    """
    真實的 GCal API client。
    每個 user 一個 instance（持有各自的 credentials）。
    """

    def __init__(
        self,
        refresh_token_enc: bytes,
        client_id: str,
        client_secret: str,
    ):
        self._refresh_token_enc = refresh_token_enc
        self._client_id = client_id
        self._client_secret = client_secret
        self._credentials: Credentials | None = None

    def _get_credentials(self) -> Credentials:
        if self._credentials and self._credentials.valid:
            return self._credentials

        refresh_token = decrypt(self._refresh_token_enc).decode("utf-8")
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            client_id=self._client_id,
            client_secret=self._client_secret,
            token_uri="https://oauth2.googleapis.com/token",
        )
        # 強制 refresh（同步，但只在 credentials 失效時才跑）
        creds.refresh(GoogleRequest())
        self._credentials = creds
        return creds

    def _build_service(self):
        return build("calendar", "v3", credentials=self._get_credentials())

    def _format_event(self, event: GCalEventInput) -> dict:
        return {
            "summary": event.summary,
            "description": event.description,
            "location": event.location,
            "colorId": event.color_id,
            "start": {
                "dateTime": event.starts_at.isoformat(),
                "timeZone": str(event.starts_at.tzinfo),
            },
            "end": {
                "dateTime": event.ends_at.isoformat(),
                "timeZone": str(event.ends_at.tzinfo),
            },
        }

    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        """在執行緒池中跑同步的 GCal API（googleapiclient 是同步的）。"""
        def _insert():
            service = self._build_service()
            result = service.events().insert(
                calendarId=calendar_id,
                body=self._format_event(event),
            ).execute()
            return result

        result = await asyncio.get_event_loop().run_in_executor(None, _insert)
        return GCalEventResult(
            gcal_event_id=result["id"],
            gcal_html_link=result.get("htmlLink", ""),
            gcal_updated=result.get("updated", ""),
        )

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        def _update():
            service = self._build_service()
            result = service.events().update(
                calendarId=calendar_id,
                eventId=gcal_event_id,
                body=self._format_event(event),
            ).execute()
            return result

        result = await asyncio.get_event_loop().run_in_executor(None, _update)
        return GCalEventResult(
            gcal_event_id=result["id"],
            gcal_html_link=result.get("htmlLink", ""),
            gcal_updated=result.get("updated", ""),
        )

    async def delete_event(
        self, calendar_id: str, gcal_event_id: str
    ) -> None:
        def _delete():
            service = self._build_service()
            service.events().delete(
                calendarId=calendar_id,
                eventId=gcal_event_id,
            ).execute()

        await asyncio.get_event_loop().run_in_executor(None, _delete)
```

### 4.3 Client Factory

```python
# app/services/integrations/google_calendar.py（底部新增）
from app.config import settings


def build_gcal_client(refresh_token_enc: bytes) -> GoogleCalendarClient:
    """
    從 DB 取出加密 token 後，用這個 factory 建立 client。
    """
    return GoogleCalendarClient(
        refresh_token_enc=refresh_token_enc,
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )


class MockGCalClient:
    """
    測試用 mock。記錄所有呼叫，不發 HTTP。
    """
    def __init__(self):
        self.inserted: list[tuple[str, GCalEventInput]] = []
        self.updated: list[tuple[str, str, GCalEventInput]] = []
        self.deleted: list[tuple[str, str]] = []
        self._event_counter = 0

    async def insert_event(
        self, calendar_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        self.inserted.append((calendar_id, event))
        self._event_counter += 1
        return GCalEventResult(
            gcal_event_id=f"mock_gcal_id_{self._event_counter}",
            gcal_html_link=f"https://calendar.google.com/mock/{self._event_counter}",
            gcal_updated="2026-04-21T00:00:00Z",
        )

    async def update_event(
        self, calendar_id: str, gcal_event_id: str, event: GCalEventInput
    ) -> GCalEventResult:
        self.updated.append((calendar_id, gcal_event_id, event))
        return GCalEventResult(
            gcal_event_id=gcal_event_id,
            gcal_html_link=f"https://calendar.google.com/mock/{gcal_event_id}",
            gcal_updated="2026-04-21T00:00:00Z",
        )

    async def delete_event(self, calendar_id: str, gcal_event_id: str) -> None:
        self.deleted.append((calendar_id, gcal_event_id))
```

---

## 5. GCal Sync Service（`app/services/gcal_sync_service.py`）

### 5.1 事件標題格式

```python
def build_event_summary(
    custodian_label: str,   # "我" 或 "對方"（從 user 關係判斷）
    child_display_name: str | None,
    case_name: str,
) -> str:
    """
    格式：[共親職] {小孩名} - {監護方}監護
    若多個小孩：[共親職] 全部小孩 - {監護方}監護
    """
    child_part = child_display_name or "全部小孩"
    return f"[共親職] {child_part} - {custodian_label}監護"
```

### 5.2 主要同步函數

```python
# app/services/gcal_sync_service.py
import time
from datetime import datetime, timezone as dt_tz
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.custody_event import CustodyEvent
from app.models.user import User
from app.models.family_case import FamilyCase
from app.models.child import Child
from app.models.gcal_sync_log import GCalSyncLog  # 對應 Migration 012 的 ORM
from app.services.integrations.google_calendar import (
    GCalClientProtocol, GCalEventInput, build_gcal_client
)
from app.config import settings


GCAL_TIMEOUT_SECONDS = 5
CALENDAR_ID = "primary"   # 預設寫入使用者的主日曆


async def sync_event_to_gcal(
    event: CustodyEvent,
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,  # None 時自動建立真實 client
) -> dict:
    """
    把單一 custody_event 同步到指定 user 的 GCal。
    回傳 {"status": "success"|"failed"|"skipped", "gcal_event_id": str|None}

    skipped 情境：user 沒有授予 Calendar 權限、或 token 為空。
    """
    start_ms = time.monotonic()

    # 1. 檢查 user 是否授予 Calendar 權限
    if not user.gcal_scope_granted or not user.google_refresh_token_enc:
        await _log_sync(db, event.id, user.id, "insert", "skipped",
                        error_message="gcal_scope_not_granted")
        return {"status": "skipped", "gcal_event_id": None}

    # 2. 建立 client
    if gcal_client is None:
        gcal_client = build_gcal_client(user.google_refresh_token_enc)

    # 3. 取相關資料（case name、child name）
    case = await db.get(FamilyCase, event.case_id)
    child = await db.get(Child, event.child_id) if event.child_id else None

    # 4. 決定 custodian_label
    custodian_label = "我" if str(event.custodian_id) == str(user.id) else "對方"

    # 5. 組裝 GCal 事件
    gcal_input = GCalEventInput(
        summary=build_event_summary(
            custodian_label=custodian_label,
            child_display_name=child.display_name if child else None,
            case_name=case.case_name if case else "",
        ),
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        description=(
            f"案件：{case.case_name if case else ''}\n"
            f"備註：{event.notes or ''}\n"
            f"地點：{event.handover_location or ''}\n"
            f"（由共親職排程 App 自動同步）"
        ),
        location=event.handover_location or "",
        color_id="1" if custodian_label == "我" else "2",
    )

    # 6. 呼叫 GCal API（含 timeout）
    try:
        import asyncio
        if event.gcal_event_id:
            result = await asyncio.wait_for(
                gcal_client.update_event(CALENDAR_ID, event.gcal_event_id, gcal_input),
                timeout=GCAL_TIMEOUT_SECONDS,
            )
            action = "update"
        else:
            result = await asyncio.wait_for(
                gcal_client.insert_event(CALENDAR_ID, gcal_input),
                timeout=GCAL_TIMEOUT_SECONDS,
            )
            action = "insert"

        # 7. 更新 custody_event 的 gcal_event_id
        event.gcal_event_id = result.gcal_event_id
        event.gcal_synced_at = datetime.now(dt_tz.utc)
        await db.flush()

        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, action, "success",
                        gcal_event_id=result.gcal_event_id,
                        duration_ms=duration_ms)

        return {"status": "success", "gcal_event_id": result.gcal_event_id}

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, "insert", "failed",
                        error_message="timeout", duration_ms=duration_ms)
        return {"status": "failed", "gcal_event_id": None}

    except Exception as e:
        duration_ms = int((time.monotonic() - start_ms) * 1000)
        await _log_sync(db, event.id, user.id, "insert", "failed",
                        error_message=str(e)[:500], duration_ms=duration_ms)
        return {"status": "failed", "gcal_event_id": None}


async def sync_events_batch(
    events: list[CustodyEvent],
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,
) -> dict:
    """
    批次同步多個事件。
    回傳 {"success": int, "failed": int, "skipped": int}
    """
    counts = {"success": 0, "failed": 0, "skipped": 0}
    for event in events:
        result = await sync_event_to_gcal(event, user, db, gcal_client)
        counts[result["status"]] += 1
    return counts


async def delete_gcal_event(
    event: CustodyEvent,
    user: User,
    db: AsyncSession,
    gcal_client: GCalClientProtocol | None = None,
) -> dict:
    """
    從 GCal 刪除對應事件（事件被取消或撤銷時呼叫）。
    """
    if not event.gcal_event_id:
        return {"status": "skipped", "reason": "no_gcal_event_id"}

    if not user.gcal_scope_granted or not user.google_refresh_token_enc:
        return {"status": "skipped", "reason": "gcal_scope_not_granted"}

    if gcal_client is None:
        gcal_client = build_gcal_client(user.google_refresh_token_enc)

    try:
        import asyncio
        await asyncio.wait_for(
            gcal_client.delete_event(CALENDAR_ID, event.gcal_event_id),
            timeout=GCAL_TIMEOUT_SECONDS,
        )
        await _log_sync(db, event.id, user.id, "delete", "success",
                        gcal_event_id=event.gcal_event_id)
        return {"status": "success"}

    except Exception as e:
        await _log_sync(db, event.id, user.id, "delete", "failed",
                        error_message=str(e)[:500])
        return {"status": "failed", "error": str(e)}


async def _log_sync(
    db: AsyncSession,
    entity_id: UUID,
    user_id: UUID,
    action: str,
    status: str,
    gcal_event_id: str | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> None:
    log = GCalSyncLog(
        entity_type="custody_event",
        entity_id=entity_id,
        user_id=user_id,
        action=action,
        status=status,
        gcal_event_id=gcal_event_id,
        error_message=error_message,
        duration_ms=duration_ms,
    )
    db.add(log)
    await db.flush()
```

---

## 6. Schedule Service 整合

在 M1.4 的 `create_rule` 和 `create_event` 完成後，**在 transaction commit 之後**觸發 GCal 同步。

**重要**：GCal 同步必須在 **transaction 提交後**才呼叫，原因是：
- GCal 同步失敗不應 rollback 業務資料
- 同步時需要讀取剛寫入的 `custody_events`（`gcal_event_id` 要回寫）

修改 `app/services/agent_service.py` 的 `handle_message`，在 `begin_nested()` 結束後加入：

```python
# app/services/agent_service.py（片段，在 begin_nested 結束後）

# begin_nested 提交（savepoint release）
# ... 現有程式碼 ...

# Transaction 提交後觸發 GCal 同步（在 begin_nested 外）
for action in actions_taken:
    if action["tool"] in ("create_recurring_custody_rule", "create_one_time_event"):
        if action["result"].get("status") == "created":
            await _trigger_gcal_sync_after_create(
                action=action,
                user=current_user,   # 需從 deps 傳入
                db=db,
            )
```

新增 helper（放在 `agent_service.py` 或獨立的 `sync_trigger.py`）：

```python
async def _trigger_gcal_sync_after_create(
    action: dict,
    user,
    db: AsyncSession,
) -> None:
    """
    建立規則或事件後，把展開的 custody_events 同步到 GCal。
    失敗不拋錯（只記 gcal_sync_log）。
    """
    from app.services.gcal_sync_service import sync_events_batch
    from app.repositories.event_repo import EventRepository
    from datetime import datetime, timezone, timedelta

    try:
        if action["tool"] == "create_recurring_custody_rule":
            rule_id = action["result"].get("rule_id")
            if not rule_id:
                return
            # 取此規則展開的所有 scheduled 事件（未來 6 個月）
            events = await EventRepository(db).list_by_rule_id(rule_id)

        elif action["tool"] == "create_one_time_event":
            event_id = action["result"].get("event_id")
            if not event_id:
                return
            from app.models.custody_event import CustodyEvent
            event = await db.get(CustodyEvent, event_id)
            events = [event] if event else []

        else:
            return

        if events:
            await sync_events_batch(events, user, db)

    except Exception as e:
        # GCal 同步失敗不影響主流程
        import logging
        logging.getLogger(__name__).warning(f"GCal sync failed: {e}")
```

同時在 `EventRepository` 新增 `list_by_rule_id` 方法：

```python
# app/repositories/event_repo.py（新增方法）
async def list_by_rule_id(self, rule_id: UUID) -> list[CustodyEvent]:
    from sqlalchemy import select, and_
    result = await self.db.execute(
        select(CustodyEvent)
        .where(
            and_(
                CustodyEvent.rule_id == rule_id,
                CustodyEvent.deleted_at.is_(None),
                CustodyEvent.status == "scheduled",
            )
        )
        .order_by(CustodyEvent.starts_at.asc())
    )
    return list(result.scalars().all())
```

**撤銷規則時刪除 GCal 事件**：在 `confirm_revocation` 裡，刪除 scheduled events 之前先呼叫 `delete_gcal_event`：

```python
# app/services/schedule_service.py confirm_revocation（補充）
from app.services.gcal_sync_service import delete_gcal_event

# 在 delete_scheduled_by_rule_after 之前
events_to_delete = await event_repo.list_scheduled_after(rule_id, cutoff)
for event in events_to_delete:
    await delete_gcal_event(event, user, db)   # user 需傳入
deleted_count = await event_repo.delete_scheduled_by_rule_after(rule_id, cutoff)
```

`confirm_revocation` 的 signature 要更新，加入 `user: User` 參數，並從 endpoint 傳入 `current_user`。

---

## 7. 新增 REST Endpoint：GCal 狀態查詢

```python
# app/api/v1/schedules.py（新增）

@router.get("/gcal-sync-status")
async def get_gcal_sync_status(
    case_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    回傳此使用者的 GCal 同步狀態摘要。
    前端用來顯示「已同步 X 個 / 失敗 Y 個」。
    """
    await _require_member(case_id, current_user.id, db)

    from sqlalchemy import select, func
    from app.models.gcal_sync_log import GCalSyncLog

    result = await db.execute(
        select(GCalSyncLog.status, func.count(GCalSyncLog.id))
        .where(GCalSyncLog.user_id == current_user.id)
        .group_by(GCalSyncLog.status)
    )
    counts = {row[0]: row[1] for row in result.all()}

    return {
        "gcal_scope_granted": current_user.gcal_scope_granted,
        "sync_counts": {
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        },
    }
```

---

## 8. 測試

### 8.1 Unit tests（mock，不需 token）

`tests/unit/test_gcal_sync.py`：

```python
import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.services.integrations.google_calendar import MockGCalClient, GCalEventResult
from app.services.gcal_sync_service import sync_event_to_gcal, sync_events_batch


def make_mock_user(gcal_granted=True, has_token=True):
    from unittest.mock import MagicMock
    user = MagicMock()
    user.id = uuid4()
    user.gcal_scope_granted = gcal_granted
    user.google_refresh_token_enc = b"encrypted_token" if has_token else None
    return user


def make_mock_event(gcal_event_id=None):
    from unittest.mock import MagicMock
    event = MagicMock()
    event.id = uuid4()
    event.case_id = uuid4()
    event.child_id = None
    event.custodian_id = uuid4()
    event.starts_at = datetime.now(timezone.utc)
    event.ends_at = datetime.now(timezone.utc) + timedelta(hours=8)
    event.notes = "test note"
    event.handover_location = None
    event.gcal_event_id = gcal_event_id
    event.gcal_synced_at = None
    return event


@pytest.mark.asyncio
async def test_sync_event_success(db_session):
    """成功同步：gcal_event_id 寫回 event。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    event = make_mock_event()

    result = await sync_event_to_gcal(event, user, db_session, gcal_client=mock_client)

    assert result["status"] == "success"
    assert result["gcal_event_id"].startswith("mock_gcal_id_")
    assert len(mock_client.inserted) == 1


@pytest.mark.asyncio
async def test_sync_skipped_no_scope(db_session):
    """沒有 Calendar 授權，回傳 skipped。"""
    mock_client = MockGCalClient()
    user = make_mock_user(gcal_granted=False)
    event = make_mock_event()

    result = await sync_event_to_gcal(event, user, db_session, gcal_client=mock_client)

    assert result["status"] == "skipped"
    assert len(mock_client.inserted) == 0


@pytest.mark.asyncio
async def test_sync_update_existing(db_session):
    """已有 gcal_event_id 時，呼叫 update 而非 insert。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    event = make_mock_event(gcal_event_id="existing_gcal_id")

    result = await sync_event_to_gcal(event, user, db_session, gcal_client=mock_client)

    assert result["status"] == "success"
    assert len(mock_client.updated) == 1
    assert len(mock_client.inserted) == 0
    assert mock_client.updated[0][1] == "existing_gcal_id"


@pytest.mark.asyncio
async def test_sync_batch(db_session):
    """批次同步：3 個事件。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    events = [make_mock_event() for _ in range(3)]

    counts = await sync_events_batch(events, user, db_session, gcal_client=mock_client)

    assert counts["success"] == 3
    assert counts["failed"] == 0
    assert len(mock_client.inserted) == 3


@pytest.mark.asyncio
async def test_sync_timeout_marked_as_failed(db_session):
    """GCal API timeout，回傳 failed，不拋 exception。"""
    import asyncio

    class TimeoutMockClient:
        async def insert_event(self, calendar_id, event):
            await asyncio.sleep(10)  # 超過 timeout

        async def update_event(self, calendar_id, gcal_event_id, event):
            await asyncio.sleep(10)

        async def delete_event(self, calendar_id, gcal_event_id):
            await asyncio.sleep(10)

    user = make_mock_user()
    event = make_mock_event()

    # 暫時把 timeout 設成 0.01 秒讓測試跑得快
    import app.services.gcal_sync_service as svc
    original_timeout = svc.GCAL_TIMEOUT_SECONDS
    svc.GCAL_TIMEOUT_SECONDS = 0.01
    try:
        result = await sync_event_to_gcal(event, user, db_session, gcal_client=TimeoutMockClient())
        assert result["status"] == "failed"
    finally:
        svc.GCAL_TIMEOUT_SECONDS = original_timeout


def test_event_summary_format():
    """標題格式測試。"""
    from app.services.gcal_sync_service import build_event_summary
    assert build_event_summary("我", "小寶", "王家") == "[共親職] 小寶 - 我監護"
    assert build_event_summary("對方", None, "王家") == "[共親職] 全部小孩 - 對方監護"
```

### 8.2 端到端測試（需真實 token，標記 `gcal_live`）

`tests/integration/test_gcal_live.py`：

```python
"""
端到端 GCal 測試。需要：
1. 有效的 GOOGLE_TEST_REFRESH_TOKEN 環境變數（從真實 OAuth 取得）
2. 標記 gcal_live 執行：pytest tests/integration/test_gcal_live.py -m gcal_live

取得測試 token 的方式：
  1. 啟動 API server（docker compose up）
  2. 瀏覽器開 http://localhost:8000/api/v1/auth/google/login
  3. 完成 Google 授權
  4. 從 DB 查詢：SELECT encode(google_refresh_token_enc, 'base64') FROM users LIMIT 1;
  5. 用 KMS decrypt 後設定環境變數（或直接用加密的 bytes 填入測試 fixture）

注意：此測試會真實寫入你的 Google Calendar，測試後自動清除。
"""
import os
import pytest
from datetime import datetime, timezone, timedelta

pytestmark = pytest.mark.gcal_live


@pytest.fixture
def real_gcal_client():
    token_b64 = os.environ.get("GOOGLE_TEST_REFRESH_TOKEN")
    if not token_b64:
        pytest.skip("GOOGLE_TEST_REFRESH_TOKEN not set")

    import base64
    from app.services.integrations.google_calendar import GoogleCalendarClient
    from app.config import settings

    return GoogleCalendarClient(
        refresh_token_enc=base64.b64decode(token_b64),
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )


@pytest.mark.asyncio
async def test_gcal_insert_and_delete(real_gcal_client):
    """建立事件後立刻刪除（驗證 API 連通）。"""
    from app.services.integrations.google_calendar import GCalEventInput

    now = datetime.now(timezone.utc)
    event_input = GCalEventInput(
        summary="[TEST] 共親職 App 測試事件（請忽略）",
        starts_at=now + timedelta(days=30),
        ends_at=now + timedelta(days=30, hours=2),
        description="自動化測試，將自動刪除",
    )

    result = await real_gcal_client.insert_event("primary", event_input)
    assert result.gcal_event_id
    print(f"Created event: {result.gcal_event_id}")

    # 立刻刪除（清理）
    await real_gcal_client.delete_event("primary", result.gcal_event_id)
    print("Deleted event")


@pytest.mark.asyncio
async def test_gcal_update(real_gcal_client):
    """建立 → 更新 → 刪除。"""
    from app.services.integrations.google_calendar import GCalEventInput

    now = datetime.now(timezone.utc)
    original = GCalEventInput(
        summary="[TEST] 原始標題",
        starts_at=now + timedelta(days=31),
        ends_at=now + timedelta(days=31, hours=2),
    )
    created = await real_gcal_client.insert_event("primary", original)

    updated_input = GCalEventInput(
        summary="[TEST] 更新後標題",
        starts_at=now + timedelta(days=31),
        ends_at=now + timedelta(days=31, hours=3),
    )
    updated = await real_gcal_client.update_event("primary", created.gcal_event_id, updated_input)
    assert updated.gcal_event_id == created.gcal_event_id

    await real_gcal_client.delete_event("primary", created.gcal_event_id)
```

---

## 9. 新增套件

```toml
# pyproject.toml 新增
google-api-python-client = "^2.120"
google-auth = "^2.29"       # M1.2 已加，確認版本符合
google-auth-oauthlib = "^1.2"
google-auth-httplib2 = "^0.2"
```

---

## 10. DoD（完成標準）

```bash
# Migration
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api alembic upgrade head"

# Unit tests（全部，不需真實 token）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/unit -v"

# Integration tests（mock GCal）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api pytest tests/integration -v"

# GCal Live tests（有真實 token 時才跑）
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  GOOGLE_TEST_REFRESH_TOKEN=xxx docker compose exec -T api \
  pytest tests/integration/test_gcal_live.py -v -m gcal_live"
```

**驗證項目**：

**Migration**
- [ ] `alembic upgrade head` 成功，`gcal_sync_log` 表建立

**Unit tests（mock）**
- [ ] `test_sync_event_success`：MockGCalClient 的 inserted 有 1 筆
- [ ] `test_sync_skipped_no_scope`：沒授權的 user，inserted 為 0
- [ ] `test_sync_update_existing`：已有 gcal_event_id 時呼叫 update
- [ ] `test_sync_batch`：3 個事件全 success
- [ ] `test_sync_timeout_marked_as_failed`：timeout 回 failed，不拋 exception
- [ ] `test_event_summary_format`：標題格式正確

**整合：Agent → GCal**
- [ ] 用 Agent 建立週期規則後，`gcal_sync_log` 有對應 success 紀錄（mock）
- [ ] 撤銷規則後，被刪除的 custody_events 在 `gcal_sync_log` 有 delete 紀錄

**M1.3 / M1.4 Evals 仍全綠**
- [ ] `pytest tests/agent_evals -v -m eval` 全部通過（GCal 同步是副作用，不影響 eval）

**GCal Live（有 token 時）**
- [ ] `test_gcal_insert_and_delete`：真實事件建立並刪除成功
- [ ] `test_gcal_update`：標題更新後 event id 不變

---

## 11. 給 Claude Code 的注意事項

1. **GCal 同步在 transaction 外呼叫**：`_trigger_gcal_sync_after_create` 必須在 `begin_nested()` 的 savepoint release 之後執行。若在 savepoint 內呼叫，GCal 寫入 `gcal_event_id` 可能因為 rollback 消失。

2. **`googleapiclient` 是同步函式庫**：所有 GCal API 呼叫都包在 `run_in_executor` 裡，不要直接 await，否則會 block event loop。

3. **`GCalSyncLog` ORM model 要自行建立**：Migration 012 定義了表結構，但 `app/models/gcal_sync_log.py` 需要對應的 SQLAlchemy ORM class，不要忘記。

4. **`confirm_revocation` 的 signature 變了**：要加入 `user: User` 參數，對應的 endpoint 要傳入 `current_user`。

5. **mock 測試的 `db_session` fixture**：`make_mock_event` 的 flush 呼叫（`event.gcal_synced_at` 和 `event.gcal_event_id` 回寫）需要 db_session 支援。如果測試中用的是 MagicMock event，flush 會失敗。建議用真實的 seeded event 或在測試 fixture 裡建立真實事件。

6. **`list_by_rule_id` 方法要加進 `EventRepository`**：M1.4 沒有這個方法，這是 M1.5 新增的。

7. **`list_scheduled_after` 也要加進 `EventRepository`**：給 `confirm_revocation` 在刪除前先取出要清理的事件清單用。
