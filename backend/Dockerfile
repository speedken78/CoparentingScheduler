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