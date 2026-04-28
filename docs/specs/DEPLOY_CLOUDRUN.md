# DEPLOY_CLOUDRUN.md｜GCP Cloud Run 部署規格書

> 本文件涵蓋從本地 Docker → GCP Cloud Run 的完整部署流程。
> 閱讀順序：本文件 → ARCHITECTURE.md §7（環境變數）
> 完成後跑 §9 DoD，確認線上環境與本地行為一致。

---

## 0. 前置確認

```bash
# 確認 gcloud 已登入且指向正確專案
gcloud config get-value project
gcloud auth list

# 確認必要 API 已啟用
gcloud services list --enabled | grep -E "run|sql|secretmanager|artifactregistry|cloudbuild"
```

若有缺少的 API，一次啟用：

```bash
gcloud services enable \
    run.googleapis.com \
    sqladmin.googleapis.com \
    secretmanager.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com
```

---

## 1. 環境變數（全局設定）

整份文件都會用到這些變數，在 WSL2 session 開始時設定一次：

```bash
export PROJECT_ID="your-gcp-project-id"        # 填入你的 GCP 專案 ID
export REGION="asia-east1"                       # 台灣最近的 region
export SERVICE_NAME="coparenting-api"
export IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"
export AR_REPO="coparenting"                     # Artifact Registry repo 名稱
export AR_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
export DB_INSTANCE_NAME="coparenting-db"
export DB_NAME="coparenting"
export DB_USER="app_user"
```

---

## 2. Dockerfile 生產版

M1.6 已有開發版 Dockerfile，生產版需要幾個調整：

```dockerfile
# Dockerfile（替換現有版本）
FROM python:3.12-slim AS base

# WeasyPrint 系統依賴（M1.6 已確認的正確套件名）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libcairo2-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    fonts-noto-cjk \
    libffi-dev \
    libssl-dev \
    libjpeg-dev \
    libopenjp2-7 \
    # Cloud SQL Auth Proxy 需要
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先複製依賴定義，利用 Docker layer cache
COPY pyproject.toml ./
RUN pip install --no-cache-dir hatchling
COPY . .
RUN pip install --no-cache-dir -e .

# 生產環境：不跑 dev server，改用 gunicorn + uvicorn worker
RUN pip install --no-cache-dir gunicorn

# 建立非 root 使用者（安全最佳實踐）
RUN useradd --create-home --shell /bin/bash appuser
RUN chown -R appuser:appuser /app
USER appuser

# Cloud Run 預設 port 8080
ENV PORT=8080
EXPOSE 8080

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8080", \
     "--timeout", "120", \
     "--keep-alive", "5", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

**注意**：
- `--workers 2`：Cloud Run 每個 instance 2 個 worker，配合 Cloud Run 的 concurrency 設定
- `--timeout 120`：WeasyPrint PDF 生成最多 120 秒
- `USER appuser`：不以 root 跑，符合 GCP 安全建議

---

## 3. Artifact Registry 設定

```bash
# 建立 Docker repository
gcloud artifacts repositories create $AR_REPO \
    --repository-format=docker \
    --location=$REGION \
    --description="CoParenting App images"

# 設定 Docker auth
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

---

## 4. Cloud SQL 建立

```bash
# 建立 PostgreSQL 16 instance（db-f1-micro 約 $10/月，MVP 夠用）
gcloud sql instances create $DB_INSTANCE_NAME \
    --database-version=POSTGRES_16 \
    --tier=db-f1-micro \
    --region=$REGION \
    --storage-type=SSD \
    --storage-size=10GB \
    --storage-auto-increase \
    --backup-start-time=02:00 \
    --retained-backups-count=7 \
    --retained-transaction-log-days=7 \
    --availability-type=zonal

# 建立資料庫
gcloud sql databases create $DB_NAME \
    --instance=$DB_INSTANCE_NAME

# 建立使用者（密碼先設強密碼，之後存 Secret Manager）
DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "DB_PASSWORD: $DB_PASSWORD"  # 記下來，下一步存進 Secret Manager

gcloud sql users create $DB_USER \
    --instance=$DB_INSTANCE_NAME \
    --password=$DB_PASSWORD

# 取得 Cloud SQL connection name（後面會用到）
gcloud sql instances describe $DB_INSTANCE_NAME \
    --format="value(connectionName)"
# 格式：PROJECT_ID:REGION:INSTANCE_NAME
```

---

## 5. Secret Manager 設定

所有敏感設定存 Secret Manager，Cloud Run 啟動時自動注入。

```bash
# 建立所有 secrets（一次建立）
create_secret() {
    echo -n "$2" | gcloud secrets create "$1" \
        --data-file=- \
        --replication-policy=automatic
}

# 資料庫密碼（填入上一步產生的密碼）
create_secret "coparenting-db-password" "$DB_PASSWORD"

# APP_DATABASE_URL（Cloud SQL Auth Proxy 格式）
DB_CONNECTION_NAME=$(gcloud sql instances describe $DB_INSTANCE_NAME \
    --format="value(connectionName)")
APP_DB_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost/${DB_NAME}?host=/cloudsql/${DB_CONNECTION_NAME}"
create_secret "coparenting-app-database-url" "$APP_DB_URL"

# Migration 用的 superuser URL（alembic 用）
SU_DB_URL="postgresql+asyncpg://postgres:POSTGRES_PASSWORD@localhost/${DB_NAME}?host=/cloudsql/${DB_CONNECTION_NAME}"
# 先把 POSTGRES_PASSWORD 設好
gcloud sql users set-password postgres \
    --instance=$DB_INSTANCE_NAME \
    --password=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# 重新取密碼並建 secret
create_secret "coparenting-migration-database-url" "$SU_DB_URL"

# JWT Secret
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
create_secret "coparenting-jwt-secret" "$JWT_SECRET"

# Job Token
JOB_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
create_secret "coparenting-job-secret-token" "$JOB_TOKEN"

# Anthropic API Key
create_secret "coparenting-anthropic-api-key" "sk-ant-api03-你的KEY"

# Google OAuth
create_secret "coparenting-google-oauth-client-id" "你的CLIENT_ID"
create_secret "coparenting-google-oauth-client-secret" "你的CLIENT_SECRET"

# KMS 加密用的本地 key（先用 local 模式）
LOCAL_KEY=$(python3 -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())")
create_secret "coparenting-local-encrypt-key" "$LOCAL_KEY"

# 確認所有 secrets
gcloud secrets list
```

---

## 6. Service Account 權限設定

```bash
SA_EMAIL="coparenting-app@${PROJECT_ID}.iam.gserviceaccount.com"

# Secret Manager 存取（讀取 secrets）
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"

# Cloud SQL 連線
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/cloudsql.client"

# GCS（稽核錨定 + PDF 上傳，M1.7 已設，確認即可）
# 若之前沒設：
gcloud storage buckets add-iam-policy-binding gs://coparenting-audit-anchors \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator"
gcloud storage buckets add-iam-policy-binding gs://coparenting-reports \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectCreator"
```

---

## 7. 建置並推送 Docker Image

```bash
cd /mnt/d/project/CoparentingScheduler/backend

# 建置（在 WSL2 內執行）
docker build -t $AR_IMAGE:latest .

# 推送
docker push $AR_IMAGE:latest

# 或用 Cloud Build（不需要本地 Docker daemon）
gcloud builds submit \
    --tag $AR_IMAGE:latest \
    --timeout=20m
```

---

## 8. 跑 Migration（一次性，部署前執行）

Migration 用 Cloud Run Jobs 跑（不是常駐 service）：

```bash
# 取得 Cloud SQL connection name
DB_CONNECTION_NAME=$(gcloud sql instances describe $DB_INSTANCE_NAME \
    --format="value(connectionName)")

# 建立 migration job
gcloud run jobs create coparenting-migrate \
    --image=$AR_IMAGE:latest \
    --region=$REGION \
    --service-account=$SA_EMAIL \
    --set-cloudsql-instances=$DB_CONNECTION_NAME \
    --set-secrets="DATABASE_URL=coparenting-migration-database-url:latest" \
    --command="alembic" \
    --args="upgrade,head" \
    --task-timeout=300

# 執行 migration
gcloud run jobs execute coparenting-migrate \
    --region=$REGION \
    --wait

# 確認成功
gcloud run jobs executions list \
    --job=coparenting-migrate \
    --region=$REGION
```

---

## 9. 部署 Cloud Run Service

```bash
DB_CONNECTION_NAME=$(gcloud sql instances describe $DB_INSTANCE_NAME \
    --format="value(connectionName)")

gcloud run deploy $SERVICE_NAME \
    --image=$AR_IMAGE:latest \
    --region=$REGION \
    --platform=managed \
    --service-account=$SA_EMAIL \
    \
    `# Cloud SQL 連線` \
    --add-cloudsql-instances=$DB_CONNECTION_NAME \
    \
    `# Secret Manager 注入` \
    --set-secrets="\
APP_DATABASE_URL=coparenting-app-database-url:latest,\
JWT_SECRET=coparenting-jwt-secret:latest,\
JOB_SECRET_TOKEN=coparenting-job-secret-token:latest,\
ANTHROPIC_API_KEY=coparenting-anthropic-api-key:latest,\
GOOGLE_OAUTH_CLIENT_ID=coparenting-google-oauth-client-id:latest,\
GOOGLE_OAUTH_CLIENT_SECRET=coparenting-google-oauth-client-secret:latest,\
LOCAL_ENCRYPT_KEY=coparenting-local-encrypt-key:latest" \
    \
    `# 環境變數（非敏感）` \
    --set-env-vars="\
ANTHROPIC_MODEL=claude-haiku-4-5,\
GCS_BUCKET_AUDIT=coparenting-audit-anchors,\
GCS_BUCKET_REPORTS=coparenting-reports,\
PDF_STORAGE_MODE=gcs,\
KMS_MODE=local,\
ENV=production,\
GOOGLE_OAUTH_REDIRECT_URI=https://SERVICE_URL/api/v1/auth/google/callback" \
    \
    `# 效能設定` \
    --min-instances=0 \
    --max-instances=10 \
    --concurrency=80 \
    --cpu=1 \
    --memory=1Gi \
    --timeout=120 \
    \
    `# 允許未認證（FastAPI 自己做 auth）` \
    --allow-unauthenticated

# 取得 Service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region=$REGION \
    --format="value(status.url)")
echo "Service URL: $SERVICE_URL"
```

**取得 URL 後，更新 `GOOGLE_OAUTH_REDIRECT_URI`**：

```bash
gcloud run services update $SERVICE_NAME \
    --region=$REGION \
    --update-env-vars="GOOGLE_OAUTH_REDIRECT_URI=${SERVICE_URL}/api/v1/auth/google/callback"
```

同時在 GCP Console → APIs & Services → OAuth 2.0 Client IDs → 加入：
- Authorized redirect URIs：`${SERVICE_URL}/api/v1/auth/google/callback`

---

## 10. app/config.py 更新

確認 `config.py` 能從環境變數讀取 Secret Manager 注入的值：

```python
# app/config.py
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    # 資料庫
    DATABASE_URL: str = ""            # migration 用（alembic）
    APP_DATABASE_URL: str = ""        # API runtime 用

    # Auth
    JWT_SECRET: str = ""
    JOB_SECRET_TOKEN: str = ""

    # Anthropic
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"

    # Google OAuth
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # GCS
    GCS_BUCKET_AUDIT: str = "coparenting-audit-anchors"
    GCS_BUCKET_REPORTS: str = "coparenting-reports"
    PDF_STORAGE_MODE: Literal["local", "gcs"] = "local"

    # KMS
    KMS_MODE: Literal["local", "gcp"] = "local"
    LOCAL_ENCRYPT_KEY: str = ""

    # 環境
    ENV: Literal["development", "production"] = "development"
    DEBUG: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


settings = Settings()
```

---

## 11. Cloud Scheduler 建立

M1.7 只預留了 endpoint，現在真的建：

```bash
# 每小時稽核錨定
gcloud scheduler jobs create http coparenting-anchor-audit \
    --location=$REGION \
    --schedule="0 * * * *" \
    --uri="${SERVICE_URL}/api/v1/admin/jobs/anchor-audit-log" \
    --http-method=POST \
    --headers="X-Job-Token=${JOB_TOKEN}" \
    --time-zone="Asia/Taipei" \
    --attempt-deadline=60s

# 每日凌晨 2 點 RRULE 展開維護
gcloud scheduler jobs create http coparenting-expand-rules \
    --location=$REGION \
    --schedule="0 2 * * *" \
    --uri="${SERVICE_URL}/api/v1/admin/jobs/expand-rules" \
    --http-method=POST \
    --headers="X-Job-Token=${JOB_TOKEN}" \
    --time-zone="Asia/Taipei" \
    --attempt-deadline=300s

# 立刻手動觸發一次確認連通
gcloud scheduler jobs run coparenting-anchor-audit --location=$REGION
```

---

## 12. 健康檢查 Endpoint

Cloud Run 需要一個健康檢查 endpoint。在 `app/api/v1/` 新增或確認 `healthz`：

```python
# app/main.py 新增（在 router 之前）
@app.get("/healthz")
async def health_check():
    return {"status": "ok", "env": settings.ENV}

@app.get("/readyz")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """確認 DB 連線正常。"""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(503, detail=f"DB not ready: {e}")
```

---

## 13. 本地 `.env` vs 生產環境差異對照

| 設定項目 | 本地（`.env`）| 生產（Cloud Run）|
|---|---|---|
| `APP_DATABASE_URL` | `postgresql+asyncpg://app_user:...@db:5432/...` | Secret Manager（Cloud SQL Proxy 路徑）|
| `PDF_STORAGE_MODE` | `local` | `gcs` |
| `KMS_MODE` | `local` | `local`（Phase 2 前維持） |
| `GOOGLE_OAUTH_REDIRECT_URI` | `http://localhost:8000/...` | `https://<cloud-run-url>/...` |
| `ENV` | `development` | `production` |
| `DEBUG` | `true` | `false`（預設）|

---

## 14. DoD（完成標準）

```bash
# 1. 確認 Cloud Run service 跑起來
curl ${SERVICE_URL}/healthz
# 預期：{"status":"ok","env":"production"}

# 2. 確認 DB 連線
curl ${SERVICE_URL}/readyz
# 預期：{"status":"ready"}

# 3. 確認 API 基本功能
curl -X POST ${SERVICE_URL}/api/v1/auth/google/login
# 預期：{"auth_url":"https://accounts.google.com/..."}

# 4. 確認 migration 成功
gcloud run jobs executions list \
    --job=coparenting-migrate --region=$REGION
# 最新一筆 SUCCEEDED

# 5. 手動觸發錨定 Job
curl -X POST ${SERVICE_URL}/api/v1/admin/jobs/anchor-audit-log \
    -H "X-Job-Token: ${JOB_TOKEN}"
# 預期：{"status":"skipped","reason":"no_audit_log_entries"} 或 anchored
```

**驗證項目**：

**基礎設施**
- [ ] Cloud SQL instance 跑起來，`db-f1-micro` 費用合理
- [ ] Artifact Registry 有 image
- [ ] 所有 secrets 在 Secret Manager 建立完成
- [ ] Service Account 有正確權限

**部署**
- [ ] `gcloud run deploy` 成功，service 狀態 Ready
- [ ] `/healthz` 回 200
- [ ] `/readyz` 回 200（代表 DB 連線正常）
- [ ] `/api/v1/auth/google/login` 回傳 auth_url

**Auth 流程**
- [ ] 瀏覽器開 `${SERVICE_URL}/api/v1/auth/google/login` 取得 URL
- [ ] 完成 Google OAuth，callback 成功回傳 JWT token
- [ ] 用 JWT token 呼叫 `/api/v1/auth/me` 回傳使用者資訊

**Jobs**
- [ ] Cloud Scheduler 兩個 jobs 建立完成
- [ ] 手動觸發 `anchor-audit-log`，Cloud Run log 有對應記錄
- [ ] 手動觸發 `expand-rules`，回傳 processed/new_events/errors

**安全**
- [ ] Admin endpoint 無 token → 403
- [ ] 敏感環境變數不出現在 Cloud Run log（確認 `settings.ANTHROPIC_API_KEY` 沒有被 print）
- [ ] Service URL 是 HTTPS

---

## 15. 費用估算（月）

| 資源 | 規格 | 預估費用 |
|---|---|---|
| Cloud Run | 0 idle，按需計費，MVP 流量極低 | $0–5 |
| Cloud SQL | `db-f1-micro`，1 vCPU / 0.6GB | ~$10 |
| Artifact Registry | < 1GB image | ~$0.1 |
| GCS | Audit + Reports bucket | ~$0.1 |
| Cloud Scheduler | 2 jobs | ~$0.2 |
| Secret Manager | < 10 secrets | ~$0.1 |
| **合計** | | **~$11–16 / 月** |

Cloud SQL 是最大的固定成本。若要更省，開發期間可以把 Cloud SQL 停掉（`gcloud sql instances patch $DB_INSTANCE_NAME --activation-policy=NEVER`），只在測試時啟動。

---

## 16. 給 Claude Code 的注意事項

1. **`DATABASE_URL` vs `APP_DATABASE_URL`**：`alembic/env.py` 讀 `DATABASE_URL`（superuser，migration 用），API runtime 讀 `APP_DATABASE_URL`（app_user，有 BYPASSRLS）。兩個不一樣，不要搞混。

2. **Cloud SQL Auth Proxy URL 格式**：`postgresql+asyncpg://user:pass@localhost/dbname?host=/cloudsql/PROJECT:REGION:INSTANCE`。注意 `host` 是 query param，不是 URL host 部分。asyncpg 透過 Unix socket 連，不是 TCP。

3. **`gunicorn` 的 worker 數量**：Cloud Run 每個 instance 設 2 workers，但 Cloud Run 本身可以起多個 instance。`--workers 2` 配合 `--concurrency 80` 讓每個 instance 最多處理 160 個同時請求。

4. **WeasyPrint 在 Cloud Run 的字型路徑**：`fonts-noto-cjk` 在 Cloud Run（Debian）的路徑和本地 Docker 相同（`/usr/share/fonts/opentype/noto/`），不需要修改模板。

5. **`--allow-unauthenticated`**：Cloud Run 預設要求 Google IAM 認證才能呼叫。我們用 `--allow-unauthenticated` 讓 FastAPI 自己做 JWT 認證。Admin endpoint 已有 `X-Job-Token` 保護，Cloud Scheduler 呼叫不需要額外 IAM 設定。

6. **首次部署後更新 `GOOGLE_OAUTH_REDIRECT_URI`**：Cloud Run URL 在第一次 deploy 後才知道，所以要先 deploy → 取得 URL → `gcloud run services update` 更新這個環境變數 → 同時在 GCP Console 的 OAuth 設定加入這個 URL。順序不能錯，否則 OAuth callback 會失敗。
