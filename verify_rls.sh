#!/bin/bash
# 驗證 RLS：必須用非超級使用者角色（BYPASSRLS=false）才能看到 RLS 效果
set -e
cd /mnt/d/project/CoparentingScheduler/backend

echo "=== 建立測試用 PostgreSQL 角色（非超級使用者）==="
docker compose exec -T db psql -U postgres -d coparenting -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'testpass';
  END IF;
END
\$\$;

-- 給予 app_user 查詢權限
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
-- app_user 不給 BYPASSRLS，所以受 RLS 限制
" 2>&1

echo ""
echo "=== 總共有幾筆 custody_events（超級使用者全看）==="
docker compose exec -T db psql -U postgres -d coparenting -c \
  "SELECT COUNT(*) AS total_events FROM custody_events;" 2>&1

echo ""
echo "=== 取得 user_0 和 user_2 的 UUID ==="
USER0_ID=$(docker compose exec -T db psql -U postgres -d coparenting -t -c \
  "SELECT id FROM users WHERE email='test_user_0@example.com';" | tr -d ' \n')
USER2_ID=$(docker compose exec -T db psql -U postgres -d coparenting -t -c \
  "SELECT id FROM users WHERE email='test_user_2@example.com';" | tr -d ' \n')
echo "user_0: $USER0_ID"
echo "user_2: $USER2_ID"

echo ""
echo "=== RLS 測試：以 app_user 角色（受 RLS 限制）查詢 ==="
echo "--- user_0 可見事件數（應只看到 case 1 的事件）---"
docker compose exec -T db psql -U app_user -d coparenting -c \
  "SET app.current_user_id='${USER0_ID}'; SELECT COUNT(*) AS user0_visible FROM custody_events;" 2>&1

echo "--- user_2 可見事件數（應只看到 case 2 的事件）---"
docker compose exec -T db psql -U app_user -d coparenting -c \
  "SET app.current_user_id='${USER2_ID}'; SELECT COUNT(*) AS user2_visible FROM custody_events;" 2>&1

echo ""
echo "=== 結果驗證 ==="
U0=$(docker compose exec -T db psql -U app_user -d coparenting -t -c \
  "SET app.current_user_id='${USER0_ID}'; SELECT COUNT(*) FROM custody_events;" | tr -d ' \n')
U2=$(docker compose exec -T db psql -U app_user -d coparenting -t -c \
  "SET app.current_user_id='${USER2_ID}'; SELECT COUNT(*) FROM custody_events;" | tr -d ' \n')
TOTAL=$(docker compose exec -T db psql -U postgres -d coparenting -t -c \
  "SELECT COUNT(*) FROM custody_events;" | tr -d ' \n')

echo "Total events in DB: $TOTAL"
echo "user_0 sees: $U0"
echo "user_2 sees: $U2"

if [ "$U0" -lt "$TOTAL" ] && [ "$U2" -lt "$TOTAL" ] && [ "$U0" -ne "$U2" ]; then
  echo "✅ RLS 正常：兩個使用者各自只看到自己案件的事件"
elif [ "$U0" -eq "$U2" ] && [ "$U0" -eq "$TOTAL" ]; then
  echo "⚠️  RLS 未生效（可能 app_user 也有 BYPASSRLS）"
elif [ "$U0" -eq "$U2" ]; then
  echo "✅ RLS 正常：兩個使用者各自看到相同數量（各自案件的事件數相等）"
else
  echo "ℹ️  結果: user_0=$U0, user_2=$U2, total=$TOTAL"
fi
