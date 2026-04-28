# 共親職排程 App（Coparenting Scheduler）

> 這是給 **Claude Code** 用的規格書。請嚴格依照本目錄下的四份文件實作，不要自行擴充或省略。
> 若文件間有衝突，優先順序：`ARCHITECTURE.md` > `DATABASE.md` > `AGENT.md` > `ROADMAP.md`。

## 文件索引

| 檔案 | 內容 | 何時讀 |
|---|---|---|
| `ARCHITECTURE.md` | 系統分層、模組職責、資料流、技術棧 | 動工前必讀 |
| `DATABASE.md` | PostgreSQL schema、稽核層、RLS、migration | 建資料庫前必讀 |
| `AGENT.md` | System prompt、tool schemas、對話狀態機、測試案例 | 實作 AI 層前必讀 |
| `ROADMAP.md` | 分階段任務清單，每階段 DoD（Definition of Done） | 規劃 sprint 時必讀 |

## 技術棧（確定）

- **後端**：FastAPI (Python 3.12+) + SQLAlchemy 2.x + Alembic
- **資料庫**：PostgreSQL 16+
- **行動端**：React Native / Expo（TypeScript）
- **AI**：Claude Haiku 4.5，模型 ID `claude-haiku-4-5`，走 Anthropic Messages API
- **部署**：GCP Cloud Run + Cloud SQL + Cloud Storage + Pub/Sub
- **整合**：Google Calendar API、LINE Messaging API

## 給 Claude Code 的啟動 prompt

複製下面這段丟給 Claude Code：

```
請依照 /docs/specs 目錄下的規格書實作「共親職排程 App」。

實作順序：
1. 先讀 README.md 理解全貌
2. 讀 ROADMAP.md，我們從 Phase 1 Milestone 1 開始
3. 建立專案骨架時對照 ARCHITECTURE.md 的目錄結構
4. 建資料庫 migration 時嚴格照 DATABASE.md，不可自行增減欄位
5. 實作 AI Agent 時遵守 AGENT.md 的 system prompt 與 tool schema

重要規則：
- 不要自行選型。規格書指定的技術棧不可替換。
- 不要自行優化 schema。所有欄位都有法律或稽核用途。
- 寫完每個模組後跑 AGENT.md 附的測試案例，通過才算完成。
- 遇到規格書沒寫清楚的地方，停下來問我，不要猜。
```
