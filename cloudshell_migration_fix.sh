#!/usr/bin/env bash
# 移轉收尾一次做完 —— setup_new_project.sh + fix_db_auth.sh 的合併版。
#
# 用途：本機 Git Bash 的 gcloud 壞掉（抓到 Windows 安裝路徑卻用 Linux python，缺 six），
# 所以改成整段貼進 Cloud Shell 執行，不需要先把檔案傳上去。
#
# 與分開跑的差別：env var 與 secret 合併在同一次 update，只產生一個 revision。
set -euo pipefail

PROJECT_ID="project-5b4f0a01-4625-4501-989"
REGION="asia-east1"
SERVICE_NAME="coparenting-api"
SERVICE_URL="https://coparenting-api-895523470853.asia-east1.run.app"
DB_INSTANCE="coparenting-db"
DB_NAME="coparenting"
SECRET_APP_URL="coparenting-app-database-url"

gcloud config set project "$PROJECT_ID"
gcloud services enable cloudscheduler.googleapis.com run.googleapis.com

CONN_NAME=$(gcloud sql instances describe "$DB_INSTANCE" --format="value(connectionName)")
echo "Cloud SQL connectionName: $CONN_NAME"

# --- 1. 輪替 app_user 密碼 ---
# 舊密碼已貼進對話記錄，視為外洩，不沿用。
# 只取英數，避免 @ : / ? 等字元破壞 DSN 解析。
NEW_PW=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)

gcloud sql users set-password app_user \
    --instance="$DB_INSTANCE" \
    --password="$NEW_PW"

# --- 2. 寫入 Secret Manager ---
# 沿用 secret 現有格式，只換密碼。@localhost 是佔位 netloc，實際走 ?host= 的 unix socket。
# printf 不加換行：多一個 \n 會讓 DSN 解析失敗。
NEW_DSN="postgresql+asyncpg://app_user:${NEW_PW}@localhost/${DB_NAME}?host=/cloudsql/${CONN_NAME}"
printf '%s' "$NEW_DSN" | gcloud secrets versions add "$SECRET_APP_URL" --data-file=-

# --- 3. env var + secret 一起更新，產生單一新 revision ---
# GOOGLE_OAUTH_REDIRECT_URI 移轉後沒設，會 fallback 成 config.py 的 localhost:8000 預設值。
# GCS bucket 移轉時改名加了 -989 後綴（bucket 名稱全域唯一，無法沿用舊名）。
# secret 在 revision 建立時解析，不重新部署不會生效。
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --update-env-vars="\
GOOGLE_OAUTH_REDIRECT_URI=${SERVICE_URL}/api/v1/auth/google/callback,\
GCS_BUCKET_AUDIT=coparenting-audit-anchors-989,\
GCS_BUCKET_REPORTS=coparenting-reports-989" \
    --update-secrets="APP_DATABASE_URL=${SECRET_APP_URL}:latest"

# --- 4. 重建 Cloud Scheduler ---
# Scheduler 是獨立資源，不隨 Cloud Run 移轉，舊專案那兩個仍指向舊網址。
# 只建後端真的有實作的 endpoint（見 backend/app/api/v1/admin.py）。
JOB_TOKEN=$(gcloud secrets versions access latest --secret=coparenting-job-secret-token)

create_or_update_job() {
    local name=$1 schedule=$2 path=$3 deadline=$4
    local args=(
        --location="$REGION"
        --schedule="$schedule"
        --uri="${SERVICE_URL}${path}"
        --http-method=POST
        --headers="X-Job-Token=${JOB_TOKEN}"
        --time-zone="Asia/Taipei"
        --attempt-deadline="$deadline"
    )
    if gcloud scheduler jobs describe "$name" --location="$REGION" >/dev/null 2>&1; then
        gcloud scheduler jobs update http "$name" "${args[@]}"
    else
        gcloud scheduler jobs create http "$name" "${args[@]}"
    fi
}

create_or_update_job coparenting-anchor-audit "0 * * * *" \
    "/api/v1/admin/jobs/anchor-audit-log" 60s
create_or_update_job coparenting-expand-rules "0 2 * * *" \
    "/api/v1/admin/jobs/expand-rules" 300s

# --- 5. 驗證 ---
echo "--- GET /readyz ---"
curl -s -w "\n[HTTP %{http_code}]\n" "${SERVICE_URL}/readyz"
echo
echo '預期 {"status":"ready"} HTTP 200。'
echo '若出現 role "app_role" does not exist 或 permission denied to set role，'
echo '表示密碼已修好、卡在下一關：role 沒隨 dump 移轉過來。接著跑：'
echo '  gcloud sql connect coparenting-db --user=postgres --database=coparenting'
echo '  然後貼上 backend/scripts/repair_roles_after_migration.sql 的內容'

echo "--- OAuth redirect_uri ---"
curl -s "${SERVICE_URL}/api/v1/auth/google/login/mobile" \
    | grep -o 'redirect_uri=[^&]*' | sed 's/%3A/:/g; s/%2F/\//g'
echo "預期指向 ${SERVICE_URL}"
