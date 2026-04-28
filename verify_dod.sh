#!/bin/bash
set -e
cd /mnt/d/project/CoparentingScheduler/backend

echo "========================================"
echo "Step 1: alembic upgrade head (已完成)"
echo "========================================"
docker compose exec -T api alembic upgrade head 2>&1 || true

echo ""
echo "========================================"
echo "Step 2a: 跑 seed"
echo "========================================"
docker compose exec -T api python -m tests.fixtures.seed 2>&1

echo ""
echo "========================================"
echo "Step 2b: RLS 驗證"
echo "========================================"

# 取 user_0 的 UUID
USER0_ID=$(docker compose exec -T db psql -U postgres -d coparenting -t -c \
  "SELECT id FROM users WHERE email='test_user_0@example.com';" | tr -d ' \n')
echo "user_0 id: $USER0_ID"

# 以 user_0 RLS 查 custody_events（應只看到 case 1 的事件，不看到 case 2）
echo "--- user_0 可見的 custody_events 數量 ---"
docker compose exec -T db psql -U postgres -d coparenting -c \
  "SET app.current_user_id='${USER0_ID}'; SELECT COUNT(*) FROM custody_events;" 2>&1

# 取 user_2 的 UUID（屬於 case 2）
USER2_ID=$(docker compose exec -T db psql -U postgres -d coparenting -t -c \
  "SELECT id FROM users WHERE email='test_user_2@example.com';" | tr -d ' \n')
echo "user_2 id: $USER2_ID"

# 以 user_2 RLS 查：應看不到 case 1 的事件
echo "--- user_2 可見的 custody_events 數量（應與 user_0 不同）---"
docker compose exec -T db psql -U postgres -d coparenting -c \
  "SET app.current_user_id='${USER2_ID}'; SELECT COUNT(*) FROM custody_events;" 2>&1

echo ""
echo "========================================"
echo "Step 3: pytest tests/unit"
echo "========================================"
docker compose exec -T api pytest tests/unit -v 2>&1

echo ""
echo "======================================== DONE ========================================"
