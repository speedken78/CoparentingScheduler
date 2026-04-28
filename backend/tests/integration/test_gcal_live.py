"""
端到端 GCal 測試。需要：
1. 有效的 GOOGLE_TEST_REFRESH_TOKEN 環境變數（從真實 OAuth 取得）
2. 標記 gcal_live 執行：pytest tests/integration/test_gcal_live.py -m gcal_live

取得測試 token 的方式：
  1. 啟動 API server（docker compose up）
  2. 瀏覽器開 http://localhost:8000/api/v1/auth/google/login
  3. 完成 Google 授權
  4. 從 DB 查詢：SELECT encode(google_refresh_token_enc, 'base64') FROM users LIMIT 1;
  5. 用 KMS decrypt 後設定環境變數

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
