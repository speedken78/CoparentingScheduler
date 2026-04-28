# ARCHITECTURE.md｜系統架構規劃

## 1. 設計原則

1. **Agent 不直接寫 DB**：LLM 產生意圖（tool call）→ 後端 service 層驗證 → 才落庫。這是安全邊界。
2. **所有變更都進稽核軌跡**：任何修改都寫 `audit_log`，附雜湊鏈。
3. **軟刪除，絕不硬刪除**：法律紀錄不能消失。
4. **時間一律 `TIMESTAMPTZ`**：跨時區安全。
5. **單一 transaction 保證一致性**：寫業務表 + 寫 audit_log 必須在同一 DB transaction 內。

## 2. 系統分層

```
┌─────────────────────────────────────────────────────────┐
│  Client (React Native / Expo)                           │
│  - 自然語言輸入 UI                                       │
│  - 行事曆檢視                                            │
│  - 接送打卡（GPS + 照片）                                │
│  - PDF 報告檢視                                          │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTPS / JWT
                       ▼
┌─────────────────────────────────────────────────────────┐
│  API Layer (FastAPI)                                    │
│  - Auth Middleware（JWT → user_id → SET app.current_user_id）│
│  - Rate Limiting                                         │
│  - Request/Response Validation (Pydantic)                │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┬─────────────┐
         ▼             ▼             ▼             ▼
    ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Agent   │  │ Schedule │  │ Handover │  │ Report   │
    │ Service │  │ Service  │  │ Service  │  │ Service  │
    └────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘
         │             │             │             │
         └─────────────┴─────────────┴─────────────┘
                       │
                       ▼
         ┌─────────────────────────────┐
         │  Data Access Layer           │
         │  - SQLAlchemy Repositories    │
         │  - Audit Log Writer（強制）   │
         └─────────────┬────────────────┘
                       │
                       ▼
         ┌─────────────────────────────┐
         │  PostgreSQL                  │
         │  - 業務表 + RLS              │
         │  - audit_log（append-only）  │
         └─────────────┬────────────────┘
                       │ 每小時
                       ▼
         ┌─────────────────────────────┐
         │  GCS Bucket (Object Lock)    │
         │  - Audit anchors（hash 錨定）│
         └─────────────────────────────┘
```

## 3. 後端目錄結構

```
backend/
├── alembic/                    # DB migration
│   └── versions/
├── app/
│   ├── main.py                 # FastAPI 進入點
│   ├── config.py               # 環境變數、設定
│   ├── deps.py                 # Dependency injection（current_user 等）
│   │
│   ├── api/                    # API routes（薄層，只做 HTTP ↔ Service 轉換）
│   │   ├── v1/
│   │   │   ├── auth.py
│   │   │   ├── cases.py        # 家庭案件
│   │   │   ├── agent.py        # 自然語言入口
│   │   │   ├── schedules.py    # 排程 CRUD
│   │   │   ├── handovers.py    # 接送打卡
│   │   │   ├── reports.py      # PDF 產生
│   │   │   └── webhooks.py     # GCal / LINE webhook
│   │   └── __init__.py
│   │
│   ├── services/               # 業務邏輯（所有寫入必須透過這層）
│   │   ├── agent_service.py    # LLM 調用、tool dispatch、多輪對話
│   │   ├── schedule_service.py # 規則展開、衝突偵測、寫入
│   │   ├── handover_service.py
│   │   ├── report_service.py   # PDF 生成（WeasyPrint）
│   │   ├── audit_service.py    # 稽核寫入 + hash chain
│   │   └── integrations/
│   │       ├── google_calendar.py
│   │       └── line_messaging.py
│   │
│   ├── agents/                 # AI Agent 專屬
│   │   ├── prompts/
│   │   │   └── scheduler_v1.py # System prompt（見 AGENT.md）
│   │   ├── tools/
│   │   │   └── definitions.py  # Tool schemas（見 AGENT.md）
│   │   ├── dispatcher.py       # tool_use → service 呼叫的對應
│   │   └── context.py          # AgentContext（對話狀態）
│   │
│   ├── models/                 # SQLAlchemy ORM
│   │   ├── base.py
│   │   ├── user.py
│   │   ├── case.py
│   │   ├── child.py
│   │   ├── custody_rule.py
│   │   ├── custody_event.py
│   │   ├── handover.py
│   │   ├── audit_log.py
│   │   └── agent_session.py
│   │
│   ├── schemas/                # Pydantic DTOs
│   │   └── ...
│   │
│   ├── repositories/           # 資料存取（封裝 SQL）
│   │   └── ...
│   │
│   └── utils/
│       ├── hash_chain.py       # audit_log 雜湊鏈計算
│       ├── rrule_expander.py   # iCal RRULE → 具體事件
│       └── timezone.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── agent_evals/            # AGENT.md 附的測試案例
│
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml          # 本地開發用
```

## 4. 核心資料流

### 4.1 自然語言排程寫入

```
User: "我這個月一三五週帶小孩,第二週日白天"
  │
  ▼
POST /api/v1/agent/message {session_id, text}
  │
  ▼
AgentService.handle_message()
  ├─ 1. 載入 AgentContext（最近 10 條規則、最近 N 輪對話）
  ├─ 2. 呼叫 Anthropic Messages API（Haiku 4.5）
  │     with system_prompt + tools + messages
  ├─ 3. 解析回應
  │     ├─ 若 stop_reason="tool_use"：
  │     │    ├─ 分派到對應 service method
  │     │    ├─ service 執行（含衝突檢查）
  │     │    └─ 將結果塞回 messages，再呼一次 API
  │     └─ 若 stop_reason="end_turn"：回傳給使用者
  └─ 4. 全程寫 agent_session 與 audit_log
```

### 4.2 寫入 transaction 必要步驟

每次業務寫入（建規則、建事件、打卡等）**必須**在單一 DB transaction 內完成：

```python
async def create_custody_rule(...):
    async with db.transaction():
        # 1. 衝突檢查（讀現有規則/事件）
        conflicts = await detect_conflicts(...)
        if conflicts and not force:
            raise ConflictError(conflicts)

        # 2. 寫業務表
        rule = await rule_repo.insert(...)

        # 3. 展開未來 6 個月事件到 custody_events
        events = expand_rrule(rule, months=6)
        await event_repo.bulk_insert(events)

        # 4. 寫 audit_log（含 hash chain）
        await audit_service.log(
            action="create_custody_rule",
            entity=rule,
            before_state=None,
            after_state=rule.dict(),
        )

    # Transaction 提交後才觸發外部副作用
    await publish_pubsub("gcal.sync", rule.id)  # 非同步
    await publish_pubsub("line.notify", rule.id)
```

## 5. 外部整合

### 5.1 Google Calendar

- OAuth 2.0，scope: `https://www.googleapis.com/auth/calendar.events`
- 每個使用者一個 token，存加密欄位
- 雙向同步：
  - App → GCal：寫入後觸發 Pub/Sub，worker 呼叫 GCal API
  - GCal → App：webhook（Google Calendar Push Notifications），watcher 每 7 天 renew
- `custody_events.gcal_event_id` 存 GCal 事件 ID，避免重複建立

### 5.2 LINE Messaging API

**重要**：LINE Notify 已於 2025 年 4 月停止服務。改用 LINE Messaging API（需建立 Official Account）或 LINE Login + LIFF。

- Official Account + Messaging API 推送通知
- LINE Login 取得 user ID
- 通知事件：
  - 對方新增/修改規則
  - 24 小時內有交接
  - 對方未在約定時間打卡（過 15 分鐘）

### 5.3 PDF 報告

- WeasyPrint（HTML → PDF，中文字型用 Noto Sans CJK TC）
- 模板放 `app/templates/reports/`
- 每份 PDF 包含：
  - 封面（案號、期間、產生時間、產生者）
  - 排程規則摘要
  - 實際接送紀錄（附打卡時間、GPS 模糊座標）
  - 異動紀錄（從 audit_log 查詢）
  - 稽核雜湊（最後一筆 audit_log 的 row_hash + 最近一次 anchor 的 GCS 路徑）
- PDF 產生後本身也存入 GCS（Object Lock），路徑寫回 `reports` 表

## 6. 安全與隱私

- **Row-Level Security**：見 DATABASE.md §4。
- **PII 最小化**：小孩存 `display_name` 而非真實全名；位置座標保留到小數第 3 位（約 100m 精度）後再存。
- **加密**：
  - 傳輸：HTTPS only
  - 靜態：Cloud SQL 自動加密；OAuth token 用 KMS 加密後存 DB
- **防濫用（家暴場景）**：
  - 「緊急隱藏模式」：使用者可一鍵切換至「最近 7 天無資料」假頁面
  - 位置分享可關閉，關閉期間的打卡不附 GPS
  - 不實作「對方位置追蹤」這類功能
- **備份**：Cloud SQL PITR 7 天 + 每日邏輯備份到 GCS（保留 1 年）。

## 7. 環境變數

```
# .env.example
DATABASE_URL=postgresql+asyncpg://...
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CHANNEL_SECRET=...
GCS_BUCKET_AUDIT=coparenting-audit-anchors
GCS_BUCKET_REPORTS=coparenting-reports
JWT_SECRET=...
KMS_KEY_NAME=projects/.../locations/.../keyRings/.../cryptoKeys/...
```

## 8. 不在 Phase 1 做的事（明確排除）

- 多語系（只做繁體中文）
- 語音輸入
- 付款整合
- 律師協作帳號
- 區塊鏈錨定（用 GCS Object Lock 取代）
- Web 版前端（只做 React Native）
