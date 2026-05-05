# 共親職排程系統

離婚家庭共同監護的排程管理系統，整合自然語言 AI Agent、法律紀錄稽核、Google Calendar 同步。

## 技術棧

**後端**
- FastAPI + PostgreSQL 16
- Claude Haiku 4.5（自然語言排程解析）
- GCP Cloud Run + Cloud SQL

**前端**
- React Native (Expo)
- TypeScript
- Zustand (狀態管理)

## 本地開發

### 後端

```bash
cd backend
cp .env.example .env
# 編輯 .env 填入必要設定
docker compose up -d
docker compose exec api alembic upgrade head
```

### 前端

```bash
cd mobile
cp .env.example .env
# 編輯 .env 設定 API URL
npm install
npx expo start
```

## 部署

詳見 `docs/specs/DEPLOY_CLOUDRUN.md`

## 授權

MIT License
