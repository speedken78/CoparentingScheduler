"""Integration tests for PDF report generation."""
import hashlib
import pytest
from datetime import date
from pathlib import Path
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.main import app
from tests.fixtures.auth import create_test_user_and_token


async def _make_db() -> tuple[AsyncSession, object]:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory(), engine


async def _setup_user(display_name="測試使用者"):
    db, engine = await _make_db()
    try:
        user, token = await create_test_user_and_token(db, display_name=display_name)
        await db.commit()
        return str(user.id), token
    finally:
        await db.close()
        await engine.dispose()


async def _seed_case(db: AsyncSession):
    """建立最小化案件，回傳 (case_id, user_id)。"""
    user_id = uuid4()
    case_id = uuid4()
    await db.execute(text(
        "INSERT INTO users (id, email, display_name, role) VALUES (:id, :email, :name, 'parent')"
    ), {"id": str(user_id), "email": f"rpt_{user_id}@test.com", "name": "報告測試家長"})
    await db.execute(text(
        "INSERT INTO family_cases (id, case_name, custody_type, created_by) "
        "VALUES (:id, :name, 'joint', :by)"
    ), {"id": str(case_id), "name": "報告整合測試案件", "by": str(user_id)})
    await db.execute(text(
        "INSERT INTO case_memberships (id, case_id, user_id, relation) "
        "VALUES (:id, :cid, :uid, 'parent_a')"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.execute(text(
        "INSERT INTO agent_sessions (id, case_id, user_id) VALUES (:id, :cid, :uid)"
    ), {"id": str(uuid4()), "cid": str(case_id), "uid": str(user_id)})
    await db.commit()
    return case_id, user_id


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── HTML render (uses DB but no HTTP) ────────────────────────────────────────

@pytest.mark.asyncio
async def test_html_render_no_crash():
    """模板渲染不崩潰（不跑真實 WeasyPrint，只驗 HTML 輸出）。"""
    from jinja2 import Environment, FileSystemLoader
    from app.services.report_service import _fetch_report_data, TEMPLATE_DIR

    db, engine = await _make_db()
    try:
        case_id, user_id = await _seed_case(db)
        data = await _fetch_report_data(
            case_id=case_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
            requesting_user_id=user_id,
            db=db,
        )
    finally:
        await db.close()
        await engine.dispose()

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("reports/monthly.html")
    html = template.render(**data)

    assert "共親職排程系統" in html
    assert data["case_name"] in html
    assert "免責聲明" in html


@pytest.mark.asyncio
async def test_pdf_generation():
    """WeasyPrint 真實生成 PDF，驗 SHA-256 非空且檔案存在。"""
    from app.services.report_service import generate_report

    db, engine = await _make_db()
    try:
        case_id, user_id = await _seed_case(db)
        report = await generate_report(
            case_id=case_id,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
            report_type="custom_range",
            requesting_user_id=user_id,
            db=db,
        )
        await db.commit()
    finally:
        await db.close()
        await engine.dispose()

    assert report.pdf_sha256
    assert len(report.pdf_sha256) == 64
    assert report.last_audit_id >= 0
    assert Path(report.pdf_gcs_path).exists()


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_and_download_report(client):
    """完整流程：建案 → 產 PDF → 下載 PDF，驗 SHA-256 一致。"""
    user_id, token = await _setup_user("報告測試使用者")

    # 建案
    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "報告測試案件", "custody_type": "joint"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]

    # 產報告
    resp = await client.post(
        f"/api/v1/cases/{case_id}/reports/",
        json={
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "report_type": "custom_range",
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    report_data = resp.json()
    assert report_data["pdf_sha256"]
    assert len(report_data["pdf_sha256"]) == 64

    # 下載 PDF
    report_id = report_data["id"]
    dl_resp = await client.get(
        f"/api/v1/cases/{case_id}/reports/{report_id}/download",
        headers=auth_headers(token),
    )
    assert dl_resp.status_code == 200, dl_resp.text
    assert dl_resp.headers["content-type"] == "application/pdf"
    assert len(dl_resp.content) > 1000

    # SHA-256 驗證
    assert hashlib.sha256(dl_resp.content).hexdigest() == report_data["pdf_sha256"]


@pytest.mark.asyncio
async def test_report_audit_log_written(client):
    """產報告後 audit_log 有 generate_report 紀錄。"""
    user_id, token = await _setup_user("稽核日誌測試使用者")

    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "稽核測試案件", "custody_type": "joint"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    case_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/cases/{case_id}/reports/",
        json={"period_start": "2026-01-01", "period_end": "2026-03-31",
              "report_type": "custom_range"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text

    from app.models.audit_log import AuditLog
    db, engine = await _make_db()
    try:
        result = await db.execute(
            select(AuditLog).where(
                AuditLog.action == "generate_report",
                AuditLog.case_id == case_id,
            )
        )
        logs = list(result.scalars().all())
    finally:
        await db.close()
        await engine.dispose()

    assert len(logs) >= 1


@pytest.mark.asyncio
async def test_list_reports(client):
    """GET /cases/{id}/reports/ 回傳先前產生的報告。"""
    user_id, token = await _setup_user("列表測試使用者")

    resp = await client.post(
        "/api/v1/cases/",
        json={"case_name": "列表測試案件", "custody_type": "joint"},
        headers=auth_headers(token),
    )
    case_id = resp.json()["id"]

    await client.post(
        f"/api/v1/cases/{case_id}/reports/",
        json={"period_start": "2026-01-01", "period_end": "2026-01-31",
              "report_type": "monthly"},
        headers=auth_headers(token),
    )

    resp = await client.get(f"/api/v1/cases/{case_id}/reports/", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["items"]) >= 1
    assert data["items"][0]["report_type"] == "monthly"
