# DATABASE.md｜PostgreSQL Schema 規格

> 所有欄位皆為必要，Claude Code 不得自行增減。
> PostgreSQL 版本：16+
> 所有時間欄位一律 `TIMESTAMPTZ`，UTC 儲存。

## 1. Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";     -- gen_random_uuid, digest
CREATE EXTENSION IF NOT EXISTS "btree_gist";   -- 時段衝突偵測用 exclusion constraint
```

## 2. 核心業務表

### 2.1 users

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT UNIQUE NOT NULL,
    phone           TEXT,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('parent','lawyer','social_worker','admin')),
    line_user_id    TEXT UNIQUE,                          -- LINE Login sub
    google_oauth_token_enc BYTEA,                         -- KMS 加密後的 token
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
```

### 2.2 family_cases

```sql
CREATE TABLE family_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_name       TEXT NOT NULL,
    court_case_no   TEXT,                                 -- 例：113年度家親聲字第XXX號
    custody_type    TEXT NOT NULL CHECK (custody_type IN ('sole','joint','split')),
    custody_ratio   JSONB,                                -- {"parent_a": 0.5, "parent_b": 0.5}
    timezone        TEXT NOT NULL DEFAULT 'Asia/Taipei',
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);
```

### 2.3 case_memberships

```sql
CREATE TABLE case_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID NOT NULL REFERENCES family_cases(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    relation        TEXT NOT NULL CHECK (relation IN ('parent_a','parent_b','lawyer','observer')),
    permissions     JSONB NOT NULL DEFAULT '{"read":true,"write":true}'::jsonb,
    invited_by      UUID REFERENCES users(id),
    joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ,
    UNIQUE (case_id, user_id, relation)
);

CREATE INDEX idx_memberships_user ON case_memberships(user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_memberships_case ON case_memberships(case_id) WHERE revoked_at IS NULL;
```

### 2.4 children

```sql
CREATE TABLE children (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID NOT NULL REFERENCES family_cases(id),
    display_name    TEXT NOT NULL,                        -- 顯示用，不存真實全名
    birth_date      DATE NOT NULL,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);
```

### 2.5 custody_rules（週期性監護規則）

```sql
CREATE TABLE custody_rules (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id           UUID NOT NULL REFERENCES family_cases(id),
    child_id          UUID REFERENCES children(id),        -- NULL 表示全部小孩
    custodian_id      UUID NOT NULL REFERENCES users(id),
    rule_type         TEXT NOT NULL CHECK (rule_type IN
                        ('weekly','biweekly','monthly_nth_weekday','custom_rrule')),
    rrule             TEXT NOT NULL,                       -- iCal RFC 5545 RRULE
    start_time        TIME NOT NULL,
    end_time          TIME NOT NULL,
    effective_from    DATE NOT NULL,
    effective_until   DATE,
    priority          INT NOT NULL DEFAULT 100,            -- 數字小優先
    source            TEXT NOT NULL CHECK (source IN
                        ('court_order','mutual_agreement','unilateral')),
    source_document   TEXT,                                -- 來源文件 GCS 路徑
    notes             TEXT,
    created_by        UUID NOT NULL REFERENCES users(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at        TIMESTAMPTZ,
    revoked_by        UUID REFERENCES users(id),
    revoked_reason    TEXT
);

CREATE INDEX idx_rules_case_active ON custody_rules(case_id, effective_from, effective_until)
    WHERE revoked_at IS NULL;
```

### 2.6 custody_events（展開後的具體事件）

```sql
CREATE TABLE custody_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id           UUID NOT NULL REFERENCES family_cases(id),
    child_id          UUID REFERENCES children(id),
    custodian_id      UUID NOT NULL REFERENCES users(id),
    rule_id           UUID REFERENCES custody_rules(id),
    starts_at         TIMESTAMPTZ NOT NULL,
    ends_at           TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN
                        ('scheduled','confirmed','in_progress','completed',
                         'missed','disputed','cancelled')),
    handover_location TEXT,
    notes             TEXT,
    gcal_event_id     TEXT,
    gcal_synced_at    TIMESTAMPTZ,
    created_by        UUID NOT NULL REFERENCES users(id),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at        TIMESTAMPTZ,
    CHECK (ends_at > starts_at)
);

CREATE INDEX idx_events_case_time ON custody_events(case_id, starts_at, ends_at)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_events_custodian_time ON custody_events(custodian_id, starts_at)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_events_gcal ON custody_events(gcal_event_id) WHERE gcal_event_id IS NOT NULL;
```

### 2.7 handover_records（實際接送打卡）

```sql
CREATE TABLE handover_records (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id               UUID NOT NULL REFERENCES custody_events(id),
    action                 TEXT NOT NULL CHECK (action IN ('pickup','dropoff')),
    performed_by           UUID NOT NULL REFERENCES users(id),
    performed_at           TIMESTAMPTZ NOT NULL,
    location_lat           NUMERIC(8,3),                   -- 模糊到小數第 3 位（約 100m）
    location_lng           NUMERIC(8,3),
    location_accuracy_m    INT,
    photo_gcs_path         TEXT,
    counterparty_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    counterparty_confirmed_at TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_handovers_event ON handover_records(event_id);
```

### 2.8 agent_sessions（AI 對話紀錄）

```sql
CREATE TABLE agent_sessions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id           UUID NOT NULL REFERENCES family_cases(id),
    user_id           UUID NOT NULL REFERENCES users(id),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN
                        ('active','completed','abandoned'))
);

CREATE TABLE agent_messages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID NOT NULL REFERENCES agent_sessions(id),
    role              TEXT NOT NULL CHECK (role IN ('user','assistant','tool_result')),
    content           JSONB NOT NULL,                      -- Anthropic API 格式原樣
    tool_use_id       TEXT,                                -- 對應 tool_use block id
    tool_name         TEXT,
    model             TEXT,                                -- claude-haiku-4-5
    input_tokens      INT,
    output_tokens     INT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_msgs_session ON agent_messages(session_id, created_at);
```

### 2.9 reports（PDF 法律報告）

```sql
CREATE TABLE reports (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id           UUID NOT NULL REFERENCES family_cases(id),
    report_type       TEXT NOT NULL CHECK (report_type IN
                        ('monthly','custom_range','dispute','full_history')),
    period_start      DATE NOT NULL,
    period_end        DATE NOT NULL,
    generated_by      UUID NOT NULL REFERENCES users(id),
    generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pdf_gcs_path      TEXT NOT NULL,
    pdf_sha256        TEXT NOT NULL,
    last_audit_id     BIGINT NOT NULL,                     -- 報告生成時的最後一筆 audit_log id
    last_audit_hash   TEXT NOT NULL,                       -- 對應的 row_hash
    anchor_id         BIGINT REFERENCES audit_anchors(id)  -- 最近的錨定點
);
```

## 3. 稽核層（核心）

### 3.1 audit_log

```sql
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    case_id         UUID NOT NULL,
    actor_id        UUID NOT NULL,                         -- 操作者；agent 操作則記錄觸發的使用者
    action          TEXT NOT NULL,                         -- 見 §3.3
    entity_type     TEXT NOT NULL,
    entity_id       UUID NOT NULL,
    before_state    JSONB,
    after_state     JSONB,
    triggered_by    TEXT NOT NULL DEFAULT 'human'          -- human / agent / system
                    CHECK (triggered_by IN ('human','agent','system')),
    agent_session_id UUID REFERENCES agent_sessions(id),
    ip_address      INET,
    user_agent      TEXT,
    device_id       TEXT,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    prev_hash       TEXT,                                  -- 上一筆的 row_hash
    row_hash        TEXT NOT NULL                          -- SHA-256(canonical_json)
);

CREATE INDEX idx_audit_case_time ON audit_log(case_id, occurred_at);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);

-- 防篡改：禁止 UPDATE / DELETE
CREATE RULE audit_log_no_update AS ON UPDATE TO audit_log DO INSTEAD NOTHING;
CREATE RULE audit_log_no_delete AS ON DELETE TO audit_log DO INSTEAD NOTHING;
```

### 3.2 audit_anchors（外部錨定）

```sql
CREATE TABLE audit_anchors (
    id              BIGSERIAL PRIMARY KEY,
    anchored_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_audit_id   BIGINT NOT NULL,
    last_row_hash   TEXT NOT NULL,
    anchor_target   TEXT NOT NULL CHECK (anchor_target IN ('gcs','tsa')),
    anchor_proof    TEXT NOT NULL,                         -- GCS object path 或 TSA token
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_anchors_audit_id ON audit_anchors(last_audit_id);
```

### 3.3 action 列舉（完整清單）

Claude Code 實作 `audit_service` 時必須支援以下所有 action：

| action | 何時記錄 |
|---|---|
| `create_custody_rule` | 建立新規則 |
| `update_custody_rule` | 修改規則（通常是 revoke + create） |
| `revoke_custody_rule` | 撤銷規則 |
| `create_custody_event` | 建立單一事件 |
| `update_custody_event` | 修改事件時間/custodian |
| `cancel_custody_event` | 取消事件 |
| `complete_custody_event` | 標記完成 |
| `create_handover_record` | 打卡 |
| `confirm_handover_record` | 對方確認打卡 |
| `generate_report` | 產生 PDF 報告 |
| `agent_parsed_input` | Agent 解析了自然語言（記錄 reasoning） |
| `agent_clarification_asked` | Agent 主動反問 |
| `member_invited` | 邀請對方加入 |
| `member_joined` | 對方加入 |
| `member_revoked` | 撤銷成員 |

### 3.4 hash chain 演算法（Claude Code 嚴格實作）

```python
# app/utils/hash_chain.py
import hashlib
import json

def canonical_json(d: dict) -> str:
    """產生穩定序列化，key 排序、無空白。"""
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

def compute_row_hash(row: dict, prev_hash: str | None) -> str:
    """
    row 應包含 audit_log 除了 id / row_hash 以外的所有欄位。
    prev_hash 為前一筆的 row_hash，第一筆為 None。
    """
    payload = {
        "prev_hash": prev_hash or "",
        "case_id": str(row["case_id"]),
        "actor_id": str(row["actor_id"]),
        "action": row["action"],
        "entity_type": row["entity_type"],
        "entity_id": str(row["entity_id"]),
        "before_state": row.get("before_state"),
        "after_state": row.get("after_state"),
        "triggered_by": row["triggered_by"],
        "occurred_at": row["occurred_at"].isoformat(),
    }
    s = canonical_json(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
```

寫入流程：

```python
async def write_audit(db, log_data: dict) -> AuditLog:
    # 1. 取上一筆的 row_hash（同 case 的最後一筆）
    prev = await db.execute(
        select(AuditLog.row_hash)
        .where(AuditLog.case_id == log_data["case_id"])
        .order_by(AuditLog.id.desc())
        .limit(1)
        .with_for_update()                                 # 避免併發競爭
    )
    prev_hash = prev.scalar_one_or_none()

    # 2. 計算 row_hash
    log_data["prev_hash"] = prev_hash
    log_data["row_hash"] = compute_row_hash(log_data, prev_hash)

    # 3. 插入
    return await db.insert(AuditLog, log_data)
```

### 3.5 錨定 Job（每小時）

```python
# 由 Cloud Scheduler 觸發，每小時跑一次
async def anchor_audit_log():
    # 1. 取全域最後一筆 audit_log
    last = await db.execute(
        select(AuditLog.id, AuditLog.row_hash)
        .order_by(AuditLog.id.desc()).limit(1)
    )
    row = last.one_or_none()
    if not row:
        return

    # 2. 已錨定過就跳過
    exists = await db.execute(
        select(AuditAnchor.id)
        .where(AuditAnchor.last_audit_id == row.id)
    )
    if exists.scalar_one_or_none():
        return

    # 3. 寫入 GCS Bucket（開啟 Object Lock）
    content = f"{row.id}:{row.row_hash}:{datetime.utcnow().isoformat()}"
    gcs_path = f"anchors/{datetime.utcnow():%Y/%m/%d}/{row.id}.txt"
    await gcs_upload(bucket="coparenting-audit-anchors", path=gcs_path, content=content)

    # 4. 寫 audit_anchors 表
    await db.insert(AuditAnchor, {
        "last_audit_id": row.id,
        "last_row_hash": row.row_hash,
        "anchor_target": "gcs",
        "anchor_proof": f"gs://coparenting-audit-anchors/{gcs_path}",
    })
```

## 4. Row-Level Security

所有含 `case_id` 的表都要開 RLS。Claude Code 必須為以下表建立 policy：

- `family_cases`
- `case_memberships`
- `children`
- `custody_rules`
- `custody_events`
- `handover_records`
- `agent_sessions`
- `agent_messages`（透過 session 間接）
- `reports`
- `audit_log`（只允許同 case 的成員 SELECT）

範例（以 `custody_events` 為例）：

```sql
ALTER TABLE custody_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY events_case_isolation ON custody_events
    FOR ALL
    USING (
        case_id IN (
            SELECT case_id FROM case_memberships
            WHERE user_id = current_setting('app.current_user_id', true)::UUID
              AND revoked_at IS NULL
        )
    );

-- Service account（後端專用角色）要 bypass RLS 才能做系統操作
ALTER TABLE custody_events FORCE ROW LEVEL SECURITY;
-- 但 BYPASSRLS 角色不受影響
```

FastAPI 每個 request 在 dependency 裡執行：

```python
async def set_rls_user(db, user_id: UUID):
    await db.execute(text("SET LOCAL app.current_user_id = :uid"), {"uid": str(user_id)})
```

## 5. 時段衝突偵測（DB 層輔助）

用 `tstzrange` + GIST exclusion constraint 在 DB 層擋掉同一 custodian 的重疊事件：

```sql
-- 注意：這個 constraint 只防止「同一 custodian 同時段有兩筆 scheduled 事件」
-- 更複雜的業務衝突（如父母雙方都要帶同一個小孩）由 application 層處理
ALTER TABLE custody_events
    ADD CONSTRAINT custody_events_no_overlap
    EXCLUDE USING gist (
        custodian_id WITH =,
        child_id WITH =,
        tstzrange(starts_at, ends_at, '[)') WITH &&
    ) WHERE (deleted_at IS NULL AND status != 'cancelled');
```

## 6. Migration 策略

- 使用 Alembic
- 命名：`{timestamp}_{description}.py`
- Phase 1 Milestone 1 的 migration 檔案順序：
  1. `001_extensions.py` – 啟用 pgcrypto、btree_gist
  2. `002_users_and_cases.py` – users, family_cases, case_memberships
  3. `003_children_and_rules.py` – children, custody_rules
  4. `004_events_and_handovers.py` – custody_events, handover_records（含 exclusion constraint）
  5. `005_audit_log.py` – audit_log, audit_anchors（含 no-update/no-delete rules）
  6. `006_agent_tables.py` – agent_sessions, agent_messages
  7. `007_reports.py` – reports
  8. `008_rls_policies.py` – 所有 RLS policy

## 7. 測試資料（fixtures）

Claude Code 實作 `tests/fixtures/seed.py`，產生：

- 2 個測試家庭案件
- 每案各 2 位家長 + 1 位小孩
- 每案 1 條 weekly 規則 + 1 條 monthly_nth_weekday 規則
- 各展開 3 個月的 custody_events
- 少量 handover_records 與 audit_log（hash chain 完整）

## 8. Claude Code 必須遵守的 DO / DON'T

**DO**
- 所有業務寫入都透過 `audit_service.log()` 同 transaction 寫稽核
- 軟刪除一律設 `deleted_at`，查詢時過濾
- RLS 設定後用 `BYPASSRLS` 角色跑 migration 與後台 job
- `audit_log.row_hash` 用 `canonical_json` 確保一致

**DON'T**
- 不要在 audit_log 加 `UPDATE` 或 `DELETE` 邏輯
- 不要在應用層計算「下次衝突」時繞過 `custody_events_no_overlap` constraint
- 不要讓使用者輸入直接決定 `case_id` 去查資料，一律從 membership 反查
- 不要在 log 裡記錄小孩真實姓名、身分證、病歷
