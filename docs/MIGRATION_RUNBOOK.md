# 移轉到新 GCP 專案 — 收尾作業

| 項目 | 舊 | 新 |
| --- | --- | --- |
| 專案 ID | `project-baad0d1c-dd31-49a4-be9` | `project-5b4f0a01-4625-4501-989` |
| 專案編號 | `684882002963` | `895523470853` |
| Cloud Run | `coparenting-api-cejshe7hxq-de.a.run.app` | `coparenting-api-895523470853.asia-east1.run.app` |
| Cloud SQL | — | `coparenting-db` |

舊服務同時保有 legacy 的 `-hash-區碼.a.run.app` 與新式 `-專案編號.區域.run.app` 兩種網址
（`de` 是 asia-east1 的區碼），兩者指向同一個服務。Google 同意畫面顯示的是 legacy 那個。

GCP 端的 Cloud Run、Cloud SQL、GCS、Secret 已由移轉工具搬完。本文件處理**移轉工具沒涵蓋、需要人工補的部分**。

## 現況

用 `bash verify_migration.sh` 取得的實測結果：

| 項目 | 狀態 |
| --- | --- |
| 服務存活 `/health` | 正常 |
| DB 連線 `/readyz` | **失敗** — `app_user` 密碼認證不過 |
| OAuth `redirect_uri` | **失敗** — 仍是 `localhost:8000` 預設值 |
| OAuth client 歸屬 | 仍在舊專案 `684882002963` |
| 舊服務 | 仍在運作 |

`/health` 不碰 DB，所以服務看起來活著，實際上所有需要資料庫的功能都是壞的。

## 為什麼這些沒被自動搬過來

| 項目 | 原因 |
| --- | --- |
| `app_user` 密碼 | PostgreSQL 的 role 屬於 **cluster 層級**，不含在單一 database 的 dump 內 |
| `app_role` 與 GRANT | 同上 |
| `GOOGLE_OAUTH_REDIRECT_URI` | 值內嵌服務網址，換網址就失效 |
| Cloud Scheduler jobs | 獨立資源，不隨 Cloud Run 移動 |
| GCS bucket 名稱 | bucket 名稱**全域唯一**，舊名仍屬舊專案，只能改名（加 `-989` 後綴） |
| OAuth 用戶端 | 屬於舊專案的 API 憑證，不隨專案移轉 |

## 執行步驟

順序有相依性，請照順序。步驟 1–3 在 Cloud Shell 執行。

### 1. 環境變數與 Cloud Scheduler

```bash
bash setup_new_project.sh
```

設定 `GOOGLE_OAUTH_REDIRECT_URI` 與兩個 GCS bucket 名稱，並重建
`coparenting-anchor-audit`（每小時）與 `coparenting-expand-rules`（每日 02:00）兩個排程。

### 2. 修復 DB 認證

```bash
bash fix_db_auth.sh
```

重設 `app_user` 密碼，同步寫入 Cloud SQL 與 Secret Manager，再重新部署。

**執行前先確認 DSN 格式**與 secret 現有的值一致：

```bash
gcloud secrets versions access latest --secret=coparenting-app-database-url
```

腳本假設是 Cloud SQL unix socket 格式。若現有格式不同（private IP 等），
只改腳本裡 `NEW_DSN` 的密碼部分，其餘照現有格式 — 連線本來就打得到 DB，host 設定是對的。

### 3. 修復角色與授權（條件執行）

步驟 2 之後若 `/readyz` 出現 `role "app_role" does not exist` 或
`permission denied to set role`，才需要這步：

```bash
gcloud sql connect coparenting-db --user=postgres --database=coparenting
\i backend/scripts/repair_roles_after_migration.sql
```

冪等，重複執行無害。檔尾附驗證查詢。

### 4. OAuth callback 白名單（Console 手動）

**要去舊專案**，不是新專案 — OAuth 用戶端仍在 `project-baad0d1c-dd31-49a4-be9`：

```text
https://console.cloud.google.com/apis/credentials?project=project-baad0d1c-dd31-49a4-be9
```

APIs & Services → Credentials → OAuth 2.0 用戶端 → 「已授權的重新導向 URI」加入：

```text
https://coparenting-api-895523470853.asia-east1.run.app/api/v1/auth/google/callback
```

無對應 gcloud 指令，只能手動點。

### 5. 驗收

```bash
bash verify_migration.sh
```

前三項要全 `[OK]` 才能進下一步。

### 6. 重新打包 App

```bash
cd mobile
eas build --profile preview --platform android
```

`EXPO_PUBLIC_API_URL` 在**打包時**內嵌進 bundle，改 `.env` 不影響已安裝的 App。
現有手機上的版本仍連舊服務。

`.env` 被 gitignore，EAS build 不會上傳，所以
[eas.json](../mobile/eas.json) 的 `preview` / `production` 各自帶了 `env` — 兩處要一起維護。

### 7. 停用舊服務

**全部驗收通過、新版 App 確認可用之後**再做。

舊服務目前仍回 200，舊版 App 連過去不會報錯，問題會被掩蓋。但也正因如此，
在切換完成前它是有用的退路，不要太早關。

關閉前先確認舊專案的 OAuth 用戶端後續怎麼處理（見下）。

## 已知的遺留問題

**OAuth 用戶端仍在舊專案。** 目前可正常運作（OAuth client 不必與 Cloud Run 同專案），
但舊專案一旦關閉就會失效。屆時需要：

1. 在新專案建立 OAuth 2.0 用戶端
2. 更新 `coparenting-google-oauth-client-id` 與 `coparenting-google-oauth-secret`
3. 重新部署 Cloud Run（secret 在 revision 建立時解析，不重新部署不會生效）

**Cloud Run 不會自動套用新版 secret。** `gcloud secrets versions add` 之後
必須產生新 revision，否則服務繼續用舊值 —— 看起來像修好了其實沒有。

## 相關檔案

| 檔案 | 用途 |
| --- | --- |
| [setup_new_project.sh](../setup_new_project.sh) | env var 與 Cloud Scheduler |
| [fix_db_auth.sh](../fix_db_auth.sh) | `app_user` 密碼同步 |
| [backend/scripts/repair_roles_after_migration.sql](../backend/scripts/repair_roles_after_migration.sql) | 重建 role 與 GRANT |
| [verify_migration.sh](../verify_migration.sh) | 驗收（純 curl，免 gcloud）|
| [DEPLOY_CLOUDRUN.md](specs/DEPLOY_CLOUDRUN.md) | 原始部署文件 |
