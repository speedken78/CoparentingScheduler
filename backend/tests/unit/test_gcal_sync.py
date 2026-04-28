"""Unit tests for gcal_sync_service — mock DB and GCal client, no real token needed."""
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.integrations.google_calendar import MockGCalClient
from app.services.gcal_sync_service import sync_event_to_gcal, sync_events_batch


def make_mock_db():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


def make_mock_user(gcal_granted=True, has_token=True):
    user = MagicMock()
    user.id = uuid4()
    user.gcal_scope_granted = gcal_granted
    user.google_refresh_token_enc = b"encrypted_token" if has_token else None
    return user


def make_mock_event(gcal_event_id=None):
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
async def test_sync_event_success():
    """成功同步：gcal_event_id 寫回 event，mock_client.inserted 有 1 筆。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    event = make_mock_event()
    db = make_mock_db()

    result = await sync_event_to_gcal(event, user, db, gcal_client=mock_client)

    assert result["status"] == "success"
    assert result["gcal_event_id"].startswith("mock_gcal_id_")
    assert len(mock_client.inserted) == 1


@pytest.mark.asyncio
async def test_sync_skipped_no_scope():
    """沒有 Calendar 授權，回傳 skipped，不呼叫 GCal API。"""
    mock_client = MockGCalClient()
    user = make_mock_user(gcal_granted=False)
    event = make_mock_event()
    db = make_mock_db()

    result = await sync_event_to_gcal(event, user, db, gcal_client=mock_client)

    assert result["status"] == "skipped"
    assert len(mock_client.inserted) == 0


@pytest.mark.asyncio
async def test_sync_update_existing():
    """已有 gcal_event_id 時，呼叫 update 而非 insert。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    event = make_mock_event(gcal_event_id="existing_gcal_id")
    db = make_mock_db()

    result = await sync_event_to_gcal(event, user, db, gcal_client=mock_client)

    assert result["status"] == "success"
    assert len(mock_client.updated) == 1
    assert len(mock_client.inserted) == 0
    assert mock_client.updated[0][1] == "existing_gcal_id"


@pytest.mark.asyncio
async def test_sync_batch():
    """批次同步 3 個事件，全部 success。"""
    mock_client = MockGCalClient()
    user = make_mock_user()
    events = [make_mock_event() for _ in range(3)]
    db = make_mock_db()

    counts = await sync_events_batch(events, user, db, gcal_client=mock_client)

    assert counts["success"] == 3
    assert counts["failed"] == 0
    assert len(mock_client.inserted) == 3


@pytest.mark.asyncio
async def test_sync_timeout_marked_as_failed():
    """GCal API timeout，回傳 failed，不拋 exception。"""
    class TimeoutMockClient:
        async def insert_event(self, calendar_id, event):
            await asyncio.sleep(10)

        async def update_event(self, calendar_id, gcal_event_id, event):
            await asyncio.sleep(10)

        async def delete_event(self, calendar_id, gcal_event_id):
            await asyncio.sleep(10)

    user = make_mock_user()
    event = make_mock_event()
    db = make_mock_db()

    import app.services.gcal_sync_service as svc
    original_timeout = svc.GCAL_TIMEOUT_SECONDS
    svc.GCAL_TIMEOUT_SECONDS = 0.01
    try:
        result = await sync_event_to_gcal(event, user, db, gcal_client=TimeoutMockClient())
        assert result["status"] == "failed"
    finally:
        svc.GCAL_TIMEOUT_SECONDS = original_timeout


def test_event_summary_format():
    """標題格式測試。"""
    from app.services.gcal_sync_service import build_event_summary
    assert build_event_summary("我", "小寶", "王家") == "[共親職] 小寶 - 我監護"
    assert build_event_summary("對方", None, "王家") == "[共親職] 全部小孩 - 對方監護"
