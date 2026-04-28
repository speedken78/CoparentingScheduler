# ROADMAP.md｜分階段實作任務清單

> 每個 Milestone 有明確 DoD（Definition of Done）。Claude Code 必須跑完 DoD 才能進下一個。

## Phase 1：單方 MVP（預計 6–8 週）

目標：單一使用者可以用自然語言建立排程、同步 GCal、產生 PDF 報告。**不做**雙方協作、LINE、衝突偵測進階功能。

### Milestone 1.1：骨架與 DB（1 週）

- [ ] 建立 FastAPI 專案骨架（依 `ARCHITECTURE.md §3`）
- [ ] Alembic migration 001–008（依 `DATABASE.md §6`）
- [ ] RLS policy 全部啟用
- [ ] `tests/fixtures/seed.py` 產生測試資料
- [ ] Docker Compose 本機可跑起 API + PostgreSQL

**DoD**：
- `alembic upgrade head` 無錯
- 跑 seed 後，以 RLS user 身分 `SELECT * FROM custody_events` 只能看到自己案件
- `pytest tests/unit` 全綠

### Milestone 1.2：Auth 與 Case 管理（1 週）

- [ ] Email + magic link 登入（或先用 JWT + 固定測試帳號）
- [ ] `POST /api/v1/cases` 建立家庭案件
- [ ] `POST /api/v1/cases/{id}/children` 新增小孩
- [ ] 所有寫入都進 `audit_log`（`triggered_by="human"`）

**DoD**：
- 建 case + 建 child 後，`audit_log` 有兩筆，`row_hash` chain 可驗證
- RLS 測試：A 使用者無法看到 B 的案件

### Milestone 1.3：AI Agent 核心（2 週）

- [ ] 整合 Anthropic SDK，model = `claude-haiku-4-5`
- [ ] 完整實作 `AGENT.md §2` system prompt
- [ ] 完整實作 `AGENT.md §3` 所有 tools
- [ ] `AgentService.handle_message` state machine（`AGENT.md §4`）
- [ ] Dispatcher（`AGENT.md §5`）
- [ ] 啟用 prompt caching

**DoD**：
- 跑完 `AGENT.md §6` 所有測試案例，通過率 100%（A/B/C/D/E 系列）
- 每次 agent 操作在 `audit_log` 有對應紀錄，`triggered_by="agent"`，`agent_session_id` 不為 null
- `agent.loop_exceeded` 指標為 0

### Milestone 1.4：排程展開與衝突偵測（1 週）

- [ ] `rrule_expander.py` 把 `custody_rules` 展開 6 個月的 `custody_events`
- [ ] `schedule_service.detect_conflicts` 支援 `detect_conflict_before_write` tool
- [ ] `custody_events_no_overlap` exclusion constraint 啟用並通過測試

**DoD**：
- 單元測試覆蓋 5 種 RRULE 模式（weekly、biweekly、monthly_nth_weekday、含 UNTIL、含 COUNT）
- 衝突偵測測試：建立兩條重疊規則時，第二條被拒絕並回傳衝突清單

### Milestone 1.5：Google Calendar 同步（1 週）

- [ ] OAuth 流程（Google Login → 存加密 token）
- [ ] Pub/Sub 觸發的 worker 將 `custody_events` 寫入 GCal
- [ ] 寫回 `gcal_event_id` + `gcal_synced_at`
- [ ] 失敗重試（指數退避，最多 5 次）

**DoD**：
- 透過 Agent 建立一條規則後，6 個月的事件都出現在使用者的 Google Calendar
- 在 App 內修改事件時間，GCal 上對應事件同步更新

### Milestone 1.6：PDF 報告（1 週）

- [ ] WeasyPrint + Noto Sans CJK TC 字型
- [ ] 月報模板（封面、規則摘要、實際紀錄、異動紀錄、稽核雜湊）
- [ ] PDF 存 GCS Object Lock bucket
- [ ] `POST /api/v1/reports`  產生指定期間報告

**DoD**：
- 產生一份 2026-04 的月報，人工檢視格式正確
- PDF 中的 `last_audit_hash` 與當時 DB 內最後一筆 audit_log 的 row_hash 一致
- 同份資料重產 PDF 時，`pdf_sha256` 不同（因為有時間戳），但 `last_audit_hash` 相同

### Milestone 1.7：稽核錨定 Job（3 天）

- [ ] Cloud Scheduler → Cloud Run Job 每小時跑 `anchor_audit_log()`
- [ ] 寫入 GCS Bucket（已啟用 Object Lock，retention 10 年）

**DoD**：
- 每小時 GCS 有一個新錨定檔
- `audit_anchors` 表的 `last_row_hash` 與 GCS 檔內容一致

### Milestone 1.8：React Native App（2 週，可與後端平行）

- [ ] Expo 專案（TypeScript）
- [ ] 畫面：登入、案件列表、Agent 對話、行事曆月檢視、事件詳情、產生 PDF
- [ ] Agent 對話支援 clarification options（tappable buttons）

**DoD**：
- 使用者可完整走完：登入 → 建立案件 → 用自然語言建規則 → 查看行事曆 → 產生 PDF → 下載
- 基本錯誤處理（斷網、API 錯誤）

### Phase 1 整體 DoD（上線前）

- [ ] 端到端測試：3 個模擬使用者劇本完整跑過
- [ ] 安全檢查：OWASP Top 10 掃過
- [ ] 稽核鏈完整性測試：模擬從頭到尾 100 筆操作，hash chain 可重算驗證
- [ ] 成本監控：每日 AI API 花費有 dashboard
- [ ] 法律免責聲明 UI 到位（「本 App 不提供法律意見」）

---

## Phase 2：雙方協作 + LINE + 打卡（預計 4–6 週）

### Milestone 2.1：雙方協作與邀請（2 週）

- [ ] 邀請連結機制（對方用 email 或 LINE ID 加入）
- [ ] `case_memberships` 雙 parent 流程
- [ ] 規則修改需對方確認的流程（`proposal` 資料模型）
- [ ] 衝突時兩方都收到通知

### Milestone 2.2：LINE Messaging API 整合（1 週）

- [ ] LINE Official Account + Messaging API（**不要用已停用的 LINE Notify**）
- [ ] 事件觸發推送：新規則、24 小時內交接、對方未打卡
- [ ] LIFF 整合讓 LINE 內可開啟 App

### Milestone 2.3：接送打卡（1 週）

- [ ] App 內打卡介面（GPS + 可選照片）
- [ ] 座標模糊化到小數第 3 位（約 100m）
- [ ] 對方確認流程

### Milestone 2.4：爭議紀錄與進階報告（1 週）

- [ ] missed / disputed 狀態的 UI 與流程
- [ ] 爭議報告：時間線視圖，標示所有 missed / disputed 事件
- [ ] 「交接遲到統計」自動摘要（客觀數字，不做判斷）

---

## Phase 3：商業化（預計 4 週）

### Milestone 3.1：金流與方案（2 週）

- [ ] 綠界或 Stripe 串接
- [ ] 方案：免費（單方 + 每月 3 次 AI 解析）／家庭版 NT$299 ／法律版 NT$799
- [ ] 用量計費與配額

### Milestone 3.2：律師協作帳號（1 週）

- [ ] `role="lawyer"` 特殊權限（唯讀整個家庭案件）
- [ ] 律師事務所後台（管理多家庭）

### Milestone 3.3：認證文書服務（1 週）

- [ ] 產生的 PDF 加上第三方電子簽章（TSA）
- [ ] 付費單次加簽流程

---

## 不在 Roadmap 的項目（明確排除）

- Web 版前端（Phase 1–3 都不做）
- 語音輸入
- 多語系（只做繁體中文）
- 區塊鏈錨定（GCS Object Lock 已足夠）
- 對方位置追蹤（倫理問題，永不實作）

## 風險與應對

| 風險 | 應對 |
|---|---|
| LLM 解析錯誤造成錯誤排程 | 所有 agent 操作走 `detect_conflict_before_write` 與 clarification；audit_log 全程記錄，可追溯與還原 |
| 家暴加害者濫用 App 監控受害者 | Phase 1 就內建「緊急隱藏模式」與「關閉 GPS 分享」；位置永遠模糊化 |
| 法院不採納 PDF 作為證據 | 前期與家事律師合作確認格式；稽核雜湊鏈 + GCS Object Lock 錨定作為完整性佐證 |
| Anthropic API 服務中斷 | Agent 降級為「表單模式」讓使用者手動建規則 |
| 成本失控 | 啟用 prompt caching；設定每月預算警報；免費方案有 AI 解析配額 |
