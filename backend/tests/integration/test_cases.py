"""Integration tests for Case / Child CRUD endpoints, audit log, and RLS isolation."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.main import app
from app.models.audit_log import AuditLog
from tests.fixtures.auth import create_test_user_and_token


async def _make_db() -> AsyncSession:
    """Create a fresh superuser session per call (avoids event-loop pool issues)."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _setup_user(display_name="測試使用者"):
    """Create a user and access token using a fresh superuser session."""
    db, engine = await _make_db()
    try:
        user, token = await create_test_user_and_token(db, display_name=display_name)
        await db.commit()
        return str(user.id), token
    finally:
        await db.close()
        await engine.dispose()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Case creation ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_case_success(client):
    user_id, token = await _setup_user("建案測試使用者")

    resp = await client.post(
        "/api/v1/cases/",
        json={
            "case_name": "王家監護排程",
            "custody_type": "joint",
            "timezone": "Asia/Taipei",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["case_name"] == "王家監護排程"
    assert data["my_relation"] == "parent_a"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_case_writes_audit_log(client):
    user_id, token = await _setup_user("審計日誌測試使用者")

    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "審計測試案件", "custody_type": "sole"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]

    db, engine = await _make_db()
    try:
        result = await db.execute(
            select(AuditLog).where(
                AuditLog.case_id == case_id,
                AuditLog.action == "create_case",
            )
        )
        entry = result.scalar_one_or_none()
    finally:
        await db.close()
        await engine.dispose()

    assert entry is not None
    assert str(entry.entity_id) == case_id
    assert entry.triggered_by == "human"
    assert entry.before_state is None


@pytest.mark.asyncio
async def test_rls_isolation_get_case_returns_404(client):
    """user_b should get 404 when trying to access user_a's case."""
    _user_a_id, token_a = await _setup_user("使用者A")
    _user_b_id, token_b = await _setup_user("使用者B")

    # user_a creates a case
    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "A的私人案件", "custody_type": "joint"},
        headers=auth_headers(token_a),
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]

    # user_b attempts to access it — must get 404, not 403
    resp_b = await client.get(f"/api/v1/cases/{case_id}", headers=auth_headers(token_b))
    assert resp_b.status_code == 404, resp_b.text


# ── Child creation ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_child_and_audit_chain(client):
    """Create case + child, verify audit_log has both entries with correct hash chain."""
    user_id, token = await _setup_user("小孩測試使用者")

    # Create case
    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "小孩測試案件", "custody_type": "joint"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]

    # Create child
    resp2 = await client.post(
        f"/api/v1/cases/{case_id}/children",
        json={"display_name": "小寶", "birth_date": "2020-03-15", "notes": "花生過敏"},
        headers=auth_headers(token),
    )
    assert resp2.status_code == 201, resp2.text
    child_data = resp2.json()
    assert child_data["display_name"] == "小寶"
    assert child_data["age_years"] >= 5

    # Verify audit_log has create_case + create_child with hash chain
    db, engine = await _make_db()
    try:
        result = await db.execute(
            select(AuditLog)
            .where(AuditLog.case_id == case_id)
            .order_by(AuditLog.id.asc())
        )
        entries = list(result.scalars().all())
    finally:
        await db.close()
        await engine.dispose()

    assert len(entries) == 2
    assert entries[0].action == "create_case"
    assert entries[1].action == "create_child"

    # Verify hash chain: entry[1].prev_hash == entry[0].row_hash
    assert entries[1].prev_hash == entries[0].row_hash

    # Re-compute entry[0] hash to confirm it matches stored value
    from app.utils.hash_chain import compute_row_hash
    expected_hash = compute_row_hash(
        {
            "case_id": entries[0].case_id,
            "actor_id": entries[0].actor_id,
            "action": entries[0].action,
            "entity_type": entries[0].entity_type,
            "entity_id": entries[0].entity_id,
            "before_state": entries[0].before_state,
            "after_state": entries[0].after_state,
            "triggered_by": entries[0].triggered_by,
            "occurred_at": entries[0].occurred_at,
        },
        entries[0].prev_hash,
    )
    assert entries[0].row_hash == expected_hash
