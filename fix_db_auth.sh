#!/usr/bin/env bash
# 修復移轉後 app_user 密碼不一致：
#   asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "app_user"
# 重設一個新密碼，同時更新 Cloud SQL 與 Secret Manager，再重新部署讓 Cloud Run 讀到新版 secret。
# 在 Cloud Shell 執行（gcloud 已認證、專案已設為新專案）。
set -euo pipefail

PROJECT_ID="project-5b4f0a01-4625-4501-989"
REGION="asia-east1"
SERVICE_NAME="coparenting-api"
DB_INSTANCE="coparenting-db"
DB_NAME="coparenting"
SECRET_APP_URL="coparenting-app-database-url"

gcloud config set project "$PROJECT_ID"

CONN_NAME=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(connectionName)")
echo "Cloud SQL connectionName: $CONN_NAME"

# --- 1. 產生新密碼 ---
# 只用英數，避免密碼出現在 DSN 裡需要 percent-encoding 的字元（@ : / ? # 等）。
NEW_PW=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)

# --- 2. 設到 Cloud SQL 的 app_user ---
gcloud sql users set-password app_user \
    --instance="$DB_INSTANCE" \
    --password="$NEW_PW"

# --- 3. 寫入 Secret Manager 新版本 ---
# 格式沿用 secret 現有的寫法，只換密碼——現有 host 設定已證實可連到 DB
# （錯誤是 InvalidPasswordError，代表連線已走到認證階段）。
#   postgresql+asyncpg://app_user:PW@localhost/coparenting?host=/cloudsql/CONN_NAME
# @localhost 只是佔位的 netloc，實際走 ?host= 指定的 unix socket。
# 不寫尾端換行：secret 內容會被原樣當成 DSN，多一個 \n 會讓連線失敗。
NEW_DSN="postgresql+asyncpg://app_user:${NEW_PW}@localhost/${DB_NAME}?host=/cloudsql/${CONN_NAME}"
printf '%s' "$NEW_DSN" | gcloud secrets versions add "$SECRET_APP_URL" --data-file=-

# --- 4. 重新部署 ---
# Cloud Run 的 secret 在 revision 建立時解析，加了新版本不會自動生效，必須產生新 revision。
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --update-secrets="APP_DATABASE_URL=${SECRET_APP_URL}:latest"

# --- 5. 驗證 ---
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --format="value(status.url)")
echo "--- GET /readyz ---"
curl -s -w "\n[HTTP %{http_code}]\n" "${SERVICE_URL}/readyz"
echo '預期 {"status":"ready"} HTTP 200。'
echo '若出現 role "app_role" does not exist 或 permission denied，'
echo '表示 role 本身沒隨 dump 移轉過來（role 是 cluster 層級，不含在單一 DB dump 內），'
echo '需要在新 instance 重建 app_role 並把 app_user 加為成員。'
