# MILESTONE_1_2.md｜Auth、App Role、Case/Child CRUD

> 本文件是給 Claude Code 的實作規格。
> 閱讀順序：本文件 → ARCHITECTURE.md → DATABASE.md
> 完成後跑 §7 DoD，全部通過才算完成。

---

## 0. 從 1.1 繼承的修正（必讀）

Milestone 1.1 過程中發現以下問題，1.2 實作時要避免重蹈：

| 問題 | 根因 | 1.2 的對應處置 |
|---|---|---|
| `rrule>=0.1.0` 不存在 | pyproject 用了錯誤套件名稱 | 本文件用 `python-dateutil`（內建 rrule），若需獨立套件用 `rruleset` 確認版本存在再加 |
| `alembic/env.py` 讀 localhost | 預設範本未改 | 本文件的 migration 範例都從 `settings.DATABASE_URL` 讀 |
| JSONB default 的 `:true` 問題 | SQLAlchemy 把 `:` 當 bind param | 所有 JSONB default 一律用 `server_default=text("jsonb_build_object(...)")` |
| RLS self-reference 遞迴 | `case_memberships` 的 policy 查自己 | 繼續沿用 `SECURITY DEFINER` 函式 `get_user_case_ids()`，本文件的 RLS policy 都走這個函式 |

---

## 1. App Role 補強（在其他任何事之前先做）

### 1.1 為什麼需要 app_role

目前後端以 superuser 連 DB，有兩個問題：
- Superuser 自動 BYPASSRLS，但它同時有 DDL 權限（可 DROP TABLE）
- API server 一旦被 SQL injection，攻擊面是整個 DB

目標：建立一個「有 BYPASSRLS、但無 DDL 權限」的應用程式專屬角色。

### 1.2 Migration 009（新增，在 008 之後）

建立檔案 `alembic/versions/009_app_role.py`：

```python
"""009: create app_role with bypassrls, no ddl

Revision ID: 009
Revises: 008
"""
from alembic import op

def upgrade():
    op.execute("""
        -- 建立應用程式專屬角色
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
                CREATE ROLE app_role WITH
                    NOLOGIN
                    NOINHERIT
                    BYPASSRLS
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE;
            END IF;
        END
        $$;
    """)

    op.execute("""
        -- 建立可登入的應用程式使用者
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
                CREATE ROLE app_user WITH
                    LOGIN
                    NOINHERIT
                    PASSWORD 'PLACEHOLDER_CHANGE_IN_ENV'  -- 實際密碼由環境變數注入
                    NOSUPERUSER
                    NOCREATEDB
                    NOCREATEROLE;
            END IF;
        END
        $$;
    """)

    op.execute("GRANT app_role TO app_user;")

    op.execute("""
        -- 授予業務表的 DML 權限，但不給 DDL
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_role;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO app_role;
    """)

    op.execute("""
        -- audit_log 只允許 INSERT（符合 append-only 設計）
        REVOKE UPDATE, DELETE ON audit_log FROM app_role;
    """)

def downgrade():
    op.execute("REASSIGN OWNED BY app_user TO postgres;")
    op.execute("DROP ROLE IF EXISTS app_user;")
    op.execute("DROP ROLE IF EXISTS app_role;")
```

### 1.3 環境變數更新

`.env.example` 新增：

```
# Migration 時用（superuser，只在 CI/CD 或手動 migration 時用）
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/coparenting

# API server 執行時用（app_user，有 BYPASSRLS 但無 DDL）
APP_DATABASE_URL=postgresql+asyncpg://app_user:CHANGE_ME@db:5432/coparenting
APP_DB_PASSWORD=CHANGE_ME   # docker-compose 在啟動時用這個設定 app_user 密碼
```

### 1.4 database.py 修改

`app/database.py` 的 engine 改用 `APP_DATABASE_URL`：

```python
from app.config import settings

# Migration 用 DATABASE_URL（alembic/env.py 維持不變）
# API runtime 用 APP_DATABASE_URL
engine = create_async_engine(
    settings.APP_DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)
```

### 1.5 docker-compose.yml 新增初始化腳本

在 `db` service 下掛載 init script，在 PostgreSQL 首次啟動時設定 app_user 密碼：

```yaml
# docker-compose.yml（片段）
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: coparenting
      APP_DB_PASSWORD: ${APP_DB_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init_db.sh:/docker-entrypoint-initdb.d/init_db.sh
```

`scripts/init_db.sh`：

```bash
#!/bin/bash
# 只在第一次啟動時執行（資料庫為空時）
set -e
psql -v ON_ERROR_STOP=1 --username "postgres" --dbname "coparenting" <<-EOSQL
    -- app_user 的密碼由環境變數設定
    DO \$\$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            EXECUTE 'ALTER ROLE app_user PASSWORD ''' || current_setting('app.db_password') || '''';
        END IF;
    END
    \$\$;
EOSQL
```

**注意**：`init_db.sh` 只在 Docker volume 為空時執行。若 migration 009 在 `init_db.sh` 之前跑（app_user 還不存在），migration 009 的 `DO $$ IF NOT EXISTS` 設計讓它在 app_user 建立後仍可正確執行。實際順序：`init_db.sh`（建 app_user）→ `alembic upgrade head`（migration 009 設定權限）。

---

## 2. Google OAuth 流程設計

### 2.1 架構決策

選 Google OAuth 的原因：一次授權同時取得：
- 使用者身分驗證（ID token）
- Google Calendar 存取 token（offline access，含 refresh token）

這樣 Milestone 1.5 的 GCal 同步不需要再做一次 OAuth。

### 2.2 所需 Google Cloud 設定（給開發者，不是程式碼）

在 GCP Console 完成以下設定，然後把資訊填入 `.env`：

1. APIs & Services → 建立 OAuth 2.0 Client（Web application）
2. Authorized redirect URIs：`http://localhost:8000/api/v1/auth/google/callback`（開發）
3. 啟用 API：Google Calendar API
4. Scopes 需要：
   - `openid`
   - `https://www.googleapis.com/auth/userinfo.email`
   - `https://www.googleapis.com/auth/userinfo.profile`
   - `https://www.googleapis.com/auth/calendar.events`

### 2.3 新增 DB 欄位（Migration 010）

建立 `alembic/versions/010_auth_fields.py`：

```python
"""010: add oauth fields to users

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # google_sub：Google 的不可變 user ID，作為登入比對依據
    op.add_column('users', sa.Column(
        'google_sub', sa.Text(), nullable=True, unique=True
    ))

    # google_refresh_token_enc：加密後的 refresh token（KMS 加密，bytes）
    # 注意：不存 access token（短效，每次從 refresh token 換）
    op.add_column('users', sa.Column(
        'google_refresh_token_enc', sa.LargeBinary(), nullable=True
    ))

    # gcal_scope_granted：確認使用者是否授予 Calendar 權限
    op.add_column('users', sa.Column(
        'gcal_scope_granted', sa.Boolean(), nullable=False,
        server_default='false'
    ))

    # last_login_at
    op.add_column('users', sa.Column(
        'last_login_at', sa.TIMESTAMP(timezone=True), nullable=True
    ))

    op.create_index('idx_users_google_sub', 'users', ['google_sub'],
                    unique=True,
                    postgresql_where=sa.text("google_sub IS NOT NULL"))

def downgrade():
    op.drop_index('idx_users_google_sub', 'users')
    op.drop_column('users', 'last_login_at')
    op.drop_column('users', 'gcal_scope_granted')
    op.drop_column('users', 'google_refresh_token_enc')
    op.drop_column('users', 'google_sub')
```

### 2.4 JWT 設計

App 自己的 session 用 JWT（不依賴 Google session）：

```python
# app/utils/jwt_utils.py
from datetime import datetime, timedelta, timezone
import jwt
from app.config import settings

ACCESS_TOKEN_EXPIRE = timedelta(hours=1)
REFRESH_TOKEN_EXPIRE = timedelta(days=30)

def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + ACCESS_TOKEN_EXPIRE,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + REFRESH_TOKEN_EXPIRE,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

def decode_token(token: str) -> dict:
    # 若 expired 或 invalid 會拋出 jwt.ExpiredSignatureError / jwt.InvalidTokenError
    return jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
```

### 2.5 Auth API Endpoints

#### `GET /api/v1/auth/google/login`

回傳 Google OAuth 授權 URL，前端導向此 URL。

Request：無

Response `200`：
```json
{
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?..."
}
```

實作：
```python
from google_auth_oauthlib.flow import Flow

def build_flow() -> Flow:
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )

@router.get("/google/login")
async def google_login():
    flow = build_flow()
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",      # 取得 refresh token
        prompt="consent",           # 強制顯示同意畫面（確保每次都給 refresh token）
        include_granted_scopes="true",
    )
    # state 存 Redis 或加密 cookie，防 CSRF（MVP 可先用加密 cookie）
    return {"auth_url": auth_url}
```

---

#### `GET /api/v1/auth/google/callback`

Google 授權後的回調端點。

Query params：`code`、`state`

Response `200`：
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "user": {
    "id": "uuid",
    "display_name": "王小明",
    "email": "user@gmail.com",
    "gcal_scope_granted": true
  }
}
```

實作邏輯（**必須嚴格依此順序**）：

```python
@router.get("/google/callback")
async def google_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    # 1. 驗證 state（CSRF 防護）
    verify_state(state)

    # 2. 用 code 換取 Google tokens
    flow = build_flow()
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    flow.fetch_token(code=code)
    credentials = flow.credentials

    # 3. 取得 Google userinfo
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        google_requests.Request(),
        settings.GOOGLE_OAUTH_CLIENT_ID
    )
    google_sub = id_info["sub"]
    email = id_info["email"]
    display_name = id_info.get("name", email.split("@")[0])

    # 4. Upsert user（用 google_sub 比對，不用 email，避免帳號衝突）
    user = await user_repo.upsert_by_google_sub(
        db,
        google_sub=google_sub,
        email=email,
        display_name=display_name,
        refresh_token_enc=encrypt_with_kms(credentials.refresh_token),
        gcal_scope_granted=("https://www.googleapis.com/auth/calendar.events"
                            in (credentials.scopes or [])),
    )

    # 5. 寫 audit_log
    await audit_service.log(db, action="user_login", entity_type="user",
                            entity_id=user.id, actor_id=user.id,
                            after_state={"method": "google_oauth"},
                            triggered_by="human")

    # 6. 產生 App JWT
    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": UserResponse.from_orm(user),
    }
```

**重要**：`credentials.refresh_token` 只在第一次授權時出現。若使用者已授權過，Google 不會再回傳 refresh_token（除非用了 `prompt="consent"`）。上面的實作已加了 `prompt="consent"` 確保每次都拿到。若 `credentials.refresh_token` 為 None，沿用 DB 既有的加密 token，不要覆蓋。

---

#### `POST /api/v1/auth/refresh`

用 App refresh token 換新的 access token。

Request body：
```json
{"refresh_token": "eyJ..."}
```

Response `200`：
```json
{"access_token": "eyJ..."}
```

實作：decode refresh token → 驗 type="refresh" → 回傳新 access token。不要重新聯絡 Google。

---

#### `GET /api/v1/auth/me`

取得當前登入使用者資訊。

Header：`Authorization: Bearer <access_token>`

Response `200`：
```json
{
  "id": "uuid",
  "display_name": "王小明",
  "email": "user@gmail.com",
  "role": "parent",
  "gcal_scope_granted": true,
  "created_at": "2026-04-01T08:00:00+08:00"
}
```

---

### 2.6 deps.py：current_user dependency

所有需要 auth 的 endpoint 都用這個 dependency：

```python
# app/deps.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.utils.jwt_utils import decode_token
from app.repositories.user_repo import UserRepository
from app.database import get_db
import jwt

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # RLS 設定：每個 request 都要執行
    await db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": user_id})

    user = await UserRepository(db).get_by_id(user_id)
    if not user or user.deleted_at:
        raise HTTPException(status_code=401, detail="User not found")
    return user
```

**注意**：`SET LOCAL app.current_user_id` 必須在每個 request 的 DB session 開始時執行。`SET LOCAL` 的作用範圍是當前 transaction，AsyncSession 預設 autobegin，所以每個 request 都會在新 transaction 內執行這個設定。

---

## 3. Case / Child CRUD

### 3.1 統一錯誤格式

所有 API 的錯誤回應統一格式（在 `main.py` 加 exception handler）：

```json
{
  "error": {
    "code": "CASE_NOT_FOUND",
    "message": "找不到指定的家庭案件",
    "detail": null
  }
}
```

錯誤碼列舉（`app/utils/errors.py`）：

```python
class ErrorCode:
    # Auth
    UNAUTHORIZED = "UNAUTHORIZED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    FORBIDDEN = "FORBIDDEN"

    # Case
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    CASE_ALREADY_MEMBER = "CASE_ALREADY_MEMBER"

    # Child
    CHILD_NOT_FOUND = "CHILD_NOT_FOUND"

    # General
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
```

### 3.2 Family Case Endpoints

#### `POST /api/v1/cases`

建立新家庭案件。

Request body：
```json
{
  "case_name": "王家監護排程",
  "court_case_no": "113年度家親聲字第123號",
  "custody_type": "joint",
  "custody_ratio": {"parent_a": 0.5, "parent_b": 0.5},
  "timezone": "Asia/Taipei"
}
```

欄位規則：
- `case_name`：必填，1–100 字
- `court_case_no`：選填
- `custody_type`：必填，`joint` / `sole` / `split`
- `custody_ratio`：選填，`joint` 時建議填
- `timezone`：選填，預設 `Asia/Taipei`

Response `201`：
```json
{
  "id": "uuid",
  "case_name": "王家監護排程",
  "court_case_no": "113年度家親聲字第123號",
  "custody_type": "joint",
  "custody_ratio": {"parent_a": 0.5, "parent_b": 0.5},
  "timezone": "Asia/Taipei",
  "my_relation": "parent_a",
  "created_at": "2026-04-21T08:00:00+08:00"
}
```

實作邏輯（**嚴格依此順序，全在單一 transaction 內**）：

```python
@router.post("/", status_code=201)
async def create_case(
    body: CreateCaseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    async with db.begin():
        # 1. 建 family_case
        case = await case_repo.insert(db, {
            "case_name": body.case_name,
            "court_case_no": body.court_case_no,
            "custody_type": body.custody_type,
            "custody_ratio": body.custody_ratio,
            "timezone": body.timezone or "Asia/Taipei",
            "created_by": current_user.id,
        })

        # 2. 建 case_membership（建立者為 parent_a）
        membership = await membership_repo.insert(db, {
            "case_id": case.id,
            "user_id": current_user.id,
            "relation": "parent_a",
            "invited_by": current_user.id,
        })

        # 3. 寫 audit_log
        await audit_service.log(db,
            case_id=case.id,
            actor_id=current_user.id,
            action="create_case",
            entity_type="family_case",
            entity_id=case.id,
            before_state=None,
            after_state=case_to_dict(case),
            triggered_by="human",
        )

    return CaseResponse.from_orm(case, relation="parent_a")
```

---

#### `GET /api/v1/cases`

列出當前使用者所屬的所有案件。

Response `200`：
```json
{
  "items": [
    {
      "id": "uuid",
      "case_name": "王家監護排程",
      "custody_type": "joint",
      "my_relation": "parent_a",
      "member_count": 1,
      "child_count": 0,
      "created_at": "2026-04-21T08:00:00+08:00"
    }
  ]
}
```

實作：查 `case_memberships` JOIN `family_cases`，RLS 自動過濾。

---

#### `GET /api/v1/cases/{case_id}`

取得單一案件詳情。

Response `200`：同 `POST /cases` 的 response，加上 `members` 陣列：
```json
{
  "id": "uuid",
  "case_name": "...",
  "custody_type": "joint",
  "my_relation": "parent_a",
  "members": [
    {"relation": "parent_a", "display_name": "王小明", "joined_at": "..."}
  ],
  "children": [...]
}
```

Forbidden 處理：RLS 會自動讓無權限的查詢回傳空結果。在 service 層要把「空結果」轉成 `404 CASE_NOT_FOUND`（不暴露「有這個案件但你沒權」的資訊）。

---

#### `PATCH /api/v1/cases/{case_id}`

更新案件基本資訊（只允許 `parent_a` 或 `parent_b` 操作，`lawyer` / `observer` 不行）。

可更新欄位：`case_name`、`court_case_no`、`custody_ratio`

**必須寫 audit_log**，`before_state` 含修改前的完整欄位值，`after_state` 含修改後。

---

### 3.3 Child Endpoints

#### `POST /api/v1/cases/{case_id}/children`

新增小孩。

Request body：
```json
{
  "display_name": "小寶",
  "birth_date": "2020-03-15",
  "notes": "花生過敏"
}
```

欄位規則：
- `display_name`：必填，1–50 字，不可為真實全名（UI 應提示「顯示名稱，如『小寶』、『大毛』」）
- `birth_date`：必填，不可是未來日期
- `notes`：選填，200 字以內

Response `201`：
```json
{
  "id": "uuid",
  "case_id": "uuid",
  "display_name": "小寶",
  "birth_date": "2020-03-15",
  "age_years": 6,
  "notes": "花生過敏",
  "created_at": "..."
}
```

實作邏輯（在 case 的 transaction 外單獨 transaction）：

```python
async with db.begin():
    # 1. 確認 case 存在且 current_user 是成員（RLS 已保護，但要確認 relation 有寫權）
    membership = await membership_repo.get(db, case_id=case_id, user_id=current_user.id)
    if not membership or membership.relation not in ("parent_a", "parent_b"):
        raise HTTPException(403, error("FORBIDDEN", "只有父母可以新增小孩"))

    # 2. 驗證 birth_date 不是未來
    if body.birth_date > date.today():
        raise HTTPException(422, error("VALIDATION_ERROR", "出生日期不可是未來日期"))

    # 3. 建 child
    child = await child_repo.insert(db, {
        "case_id": case_id,
        "display_name": body.display_name,
        "birth_date": body.birth_date,
        "notes": body.notes,
    })

    # 4. audit_log
    await audit_service.log(db,
        case_id=case_id,
        actor_id=current_user.id,
        action="create_child",
        entity_type="child",
        entity_id=child.id,
        before_state=None,
        after_state=child_to_dict(child),
        triggered_by="human",
    )
```

---

#### `GET /api/v1/cases/{case_id}/children`

列出此案件的所有小孩。

Response `200`：
```json
{
  "items": [
    {
      "id": "uuid",
      "display_name": "小寶",
      "birth_date": "2020-03-15",
      "age_years": 6,
      "notes": "花生過敏"
    }
  ]
}
```

---

#### `PATCH /api/v1/cases/{case_id}/children/{child_id}`

更新小孩資訊。可更新欄位：`display_name`、`notes`（不允許改 `birth_date`）。

**必須寫 audit_log**，before/after 都要。

---

## 4. audit_service 呼叫規範

### 4.1 函式簽名（`app/services/audit_service.py`）

```python
async def log(
    db: AsyncSession,
    *,
    case_id: UUID,
    actor_id: UUID,
    action: str,                          # 見 DATABASE.md §3.3
    entity_type: str,
    entity_id: UUID,
    before_state: dict | None = None,
    after_state: dict | None = None,
    triggered_by: Literal["human", "agent", "system"] = "human",
    agent_session_id: UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    device_id: str | None = None,
) -> AuditLog:
    ...
```

### 4.2 呼叫時機（強制規定）

每個 API handler 的以下操作都**必須**呼叫 `audit_service.log`，且必須在同一 DB transaction 內：

| 操作 | action 值 |
|---|---|
| 建立家庭案件 | `create_case` |
| 更新家庭案件 | `update_case` |
| 建立小孩 | `create_child` |
| 更新小孩 | `update_child` |
| 刪除小孩（軟刪除） | `delete_child` |
| 使用者登入 | `user_login` |
| 邀請成員 | `member_invited` |
| 成員加入 | `member_joined` |

### 4.3 before_state / after_state 的內容

- 記錄「業務欄位」，不記錄 `created_at`、`updated_at`、`deleted_at` 等系統欄位
- 不記錄以下敏感欄位：`google_refresh_token_enc`、`google_sub`（雖然 sub 不敏感，但統一排除）
- `before_state=None` 代表這是新建操作

範例：
```python
# 建立 child 的 after_state
{
    "case_id": "uuid",
    "display_name": "小寶",
    "birth_date": "2020-03-15",
    "notes": "花生過敏"
}
```

### 4.4 ip_address / user_agent 的取得

在 `deps.py` 的 `get_current_user` 之外，另外建立 request context dependency：

```python
# app/deps.py
from fastapi import Request

def get_request_context(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
```

API handler 引入：

```python
@router.post("/")
async def create_case(
    body: CreateCaseRequest,
    current_user: User = Depends(get_current_user),
    req_ctx: dict = Depends(get_request_context),
    db: AsyncSession = Depends(get_db),
):
    # ...
    await audit_service.log(db, ..., **req_ctx)
```

---

## 5. 新增套件

以下套件需要加進 `pyproject.toml`（確認版本存在再加，避免重蹈 1.1 的 rrule 問題）：

```toml
[tool.poetry.dependencies]
# Auth
google-auth = "^2.29"
google-auth-oauthlib = "^1.2"
google-auth-httplib2 = "^0.2"
PyJWT = "^2.8"

# GCP KMS（refresh token 加密用）
google-cloud-kms = "^2.21"

# 若無本地 KMS（MVP 開發環境），改用 cryptography 做 AES-256-GCM
cryptography = "^42.0"
```

**KMS 說明**：Production 用 GCP KMS；開發環境可用 `cryptography` 套件做 AES-256-GCM，密鑰從環境變數取得。建立 `app/utils/kms.py`，介面保持一致（`encrypt(plaintext: bytes) -> bytes` / `decrypt(ciphertext: bytes) -> bytes`），切換時只改實作，不改呼叫端。

開發環境的 `.env`：
```
KMS_MODE=local          # local | gcp
LOCAL_ENCRYPT_KEY=...   # 32 bytes base64，用 python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())" 產生
```

---

## 6. 新增測試

### 6.1 Unit tests

`tests/unit/test_auth.py`：
- `test_create_access_token`：產生後 decode，驗 sub / type / exp
- `test_create_refresh_token`：同上
- `test_decode_expired_token`：設過期時間在過去，驗 ExpiredSignatureError
- `test_token_type_check`：用 refresh token 當 access token，驗被拒

`tests/unit/test_kms.py`：
- `test_encrypt_decrypt_roundtrip`：加密後解密，驗原文相同
- `test_different_ciphertext`：同樣明文加密兩次，ciphertext 不同（AES-GCM nonce 是隨機的）

### 6.2 Integration tests

`tests/integration/test_cases.py`：
- 建立案件 → 驗 audit_log 有一筆 `create_case`
- 建立案件 → 另一個 user 嘗試 GET → 應得 404（RLS 過濾 + 服務層轉換）
- 建立案件 → 建小孩 → 驗 audit_log 有 `create_case` + `create_child`，hash chain 正確

### 6.3 測試不需要真實 Google OAuth

`tests/fixtures/auth.py` 提供 helper：

```python
async def create_test_user_and_token(db, display_name="測試使用者") -> tuple[User, str]:
    """直接建 user（跳過 Google OAuth），回傳 user + access_token。"""
    user = await user_repo.insert(db, {
        "email": f"test_{uuid4().hex[:6]}@test.com",
        "display_name": display_name,
        "role": "parent",
        "google_sub": f"test_sub_{uuid4().hex}",  # 假的 sub，integration test 用
    })
    token = create_access_token(str(user.id))
    return user, token
```

所有 integration test 用這個 helper，不走真實 Google OAuth 流程。

---

## 7. DoD（完成標準）

執行以下指令，全部通過才算 Milestone 1.2 完成：

```bash
# 確保在 WSL2 內的 Docker 環境中執行
wsl -d Ubuntu -u root -- bash -c "cd /mnt/d/project/CoparentingScheduler/backend && \
  docker compose exec -T api alembic upgrade head && \
  docker compose exec -T api pytest tests/unit tests/integration -v"
```

具體驗證項目：

**App Role**
- [ ] `SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname IN ('app_role','app_user');` 回傳 app_role bypassrls=t super=f，app_user bypassrls=f super=f
- [ ] API server 連線用 app_user，確認 `SELECT current_user;` 回傳 `app_user`
- [ ] app_user 無法執行 `DROP TABLE users;`（應得 permission denied）

**Auth**
- [ ] `pytest tests/unit/test_auth.py` 全綠
- [ ] `pytest tests/unit/test_kms.py` 全綠
- [ ] `GET /api/v1/auth/google/login` 回傳含 `auth_url` 的 JSON（不需真實 Google）
- [ ] `GET /api/v1/auth/me`（用 test token）回傳使用者資料

**Case / Child CRUD**
- [ ] `pytest tests/integration/test_cases.py` 全綠
- [ ] 建案件後，audit_log 有 `create_case` 一筆，`triggered_by='human'`
- [ ] 建小孩後，audit_log 有 `create_child` 一筆，hash chain 與前一筆連結正確
- [ ] RLS 隔離：user_A 的 token 無法看到 user_B 的案件（得 404，不是 403）

**Hash chain 連貫性**
- [ ] 建案件 + 建小孩後，用 `test_hash_chain.py` 的驗證邏輯重算，所有 row_hash 一致

---

## 8. 已知注意事項（Claude Code 必讀）

1. **`SET LOCAL` 的作用域**：`SET LOCAL app.current_user_id` 只在當前 transaction 有效。若同一個 DB connection 被 connection pool 複用，下一個 request 必須重新設定。`AsyncSession` 每次 request 都是獨立 session，這個問題不會發生——但不要在 session 外手動執行 raw connection 操作。

2. **Google OAuth 的 `prompt=consent`**：這會讓已授權過的使用者每次登入都看到同意畫面。MVP 可接受；Production 考慮改成「第一次 + 需要 refresh token 時才加 prompt=consent」的邏輯。

3. **refresh_token 為 None 的情況**：若使用者之前已授權但本次登入沒回傳 refresh_token（Google 的行為），不要把 None 寫進 DB，保留原有加密 token。

4. **`audit_log` 的 RLS**：Migration 008 的 audit_log policy 允許 SELECT（同 case 成員）但拒絕 INSERT（直接）。後端透過 app_role（BYPASSRLS）寫入，所以不受影響。不要改這個設計。

5. **child 的 `display_name` 不是全名**：UI 層要提示使用者輸入暱稱/小名，這是隱私設計。`display_name` 不做實名驗證。
