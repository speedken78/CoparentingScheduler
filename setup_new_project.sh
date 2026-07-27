#!/usr/bin/env bash
# 環境移轉到新 GCP 專案後，重建 Cloud Scheduler 並修正內嵌服務網址的設定。
#
# 移轉來源：project-baad0d1c-dd31-49a4-be9（編號 684882002963）
# 移轉目標：project-5b4f0a01-4625-4501-989（編號 895523470853）
#
# 前置：gcloud auth login && gcloud config set project $PROJECT_ID
set -euo pipefail

PROJECT_ID="project-5b4f0a01-4625-4501-989"
REGION="asia-east1"
SERVICE_NAME="coparenting-api"
SERVICE_URL="https://coparenting-api-895523470853.asia-east1.run.app"

gcloud config set project "$PROJECT_ID"

# --- 1. 確認必要 API 已啟用（新專案常漏這步）---
gcloud services enable cloudscheduler.googleapis.com run.googleapis.com

OLD_PROJECT_ID="project-baad0d1c-dd31-49a4-be9"   # OAuth 用戶端仍留在這裡（見 2b）
OLD_PROJECT_NUMBER="684882002963"

# --- 2. 修正內嵌舊專案資源名稱的 env var ---
# 移轉後新服務根本沒設 GOOGLE_OAUTH_REDIRECT_URI，會 fallback 成 config.py 的預設值
# http://localhost:8000/...，導致手機登入被導去 localhost。
# GCS bucket 移轉時改名加了 -989 後綴（bucket 名稱全域唯一，無法沿用舊名）。
# --update-env-vars 只覆蓋列出的 key，其他 env var 不受影響。
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" \
    --update-env-vars="\
GOOGLE_OAUTH_REDIRECT_URI=${SERVICE_URL}/api/v1/auth/google/callback,\
GCS_BUCKET_AUDIT=coparenting-audit-anchors-989,\
GCS_BUCKET_REPORTS=coparenting-reports-989"

# --- 2b. OAuth 白名單：必須在「舊專案」操作 ---
#
# 注意：OAuth 用戶端沒有跟著移轉，仍留在舊專案 $OLD_PROJECT_NUMBER。
# 驗證方式：打新服務的登入端點，看回傳 client_id 的開頭數字是哪個專案編號
#   curl -s "${SERVICE_URL}/api/v1/auth/google/login/mobile"
#   → client_id=684882002963-xxxxx.apps.googleusercontent.com  ← 舊專案編號
#
# 所以要去「舊專案」的 Console，不是新專案 —— 在新專案的憑證頁面找不到這個用戶端：
#   https://console.cloud.google.com/apis/credentials?project=project-baad0d1c-dd31-49a4-be9
#   APIs & Services > Credentials > OAuth 2.0 Client ID
#   把下列網址加進「已授權的重新導向 URI」（無對應 gcloud 指令，只能手動點）：
#     ${SERVICE_URL}/api/v1/auth/google/callback
#
# 若日後要關閉舊專案，這個用戶端會一併失效。屆時需在新專案另建 OAuth 用戶端，
# 並更新 coparenting-google-oauth-client-id / -secret 兩個 secret 後重新部署。

# --- 3. 取得 JOB_SECRET_TOKEN ---
# Scheduler 用 X-Job-Token header 呼叫 admin endpoint（見 backend/app/api/v1/admin.py:14）。
# 必須跟 Cloud Run 服務注入的值一致，否則會 403。
JOB_TOKEN=$(gcloud secrets versions access latest --secret=coparenting-job-secret-token)

# --- 4. 重建 Cloud Scheduler jobs ---
# 只建目前後端真的有實作的兩個 endpoint。
# create 若已存在會失敗，故先試 update、失敗才 create。
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

# 每小時稽核錨定
create_or_update_job coparenting-anchor-audit "0 * * * *" \
    "/api/v1/admin/jobs/anchor-audit-log" 60s

# 每日凌晨 2 點 RRULE 展開維護
create_or_update_job coparenting-expand-rules "0 2 * * *" \
    "/api/v1/admin/jobs/expand-rules" 300s

# --- 5. 驗證連通 ---
gcloud scheduler jobs run coparenting-anchor-audit --location="$REGION"
sleep 10
gcloud scheduler jobs describe coparenting-anchor-audit \
    --location="$REGION" \
    --format="value(status.code,lastAttemptTime)"

echo "--- 目前服務 env var（確認 bucket 與 redirect URI 都指向新專案）---"
gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" \
    --format="value(spec.template.spec.containers[0].env)"

echo "完成。status.code 空白或 0 表示成功；非 0 請查 Cloud Run logs。"
