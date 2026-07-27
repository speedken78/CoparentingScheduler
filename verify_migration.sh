#!/usr/bin/env bash
# 移轉後驗收：只用 curl 檢查對外行為，不需要 gcloud 認證。
# 用法：bash verify_migration.sh
set -uo pipefail   # 不用 -e，讓所有檢查都跑完再一次看結果

NEW_URL="https://coparenting-api-895523470853.asia-east1.run.app"
OLD_URL="https://coparenting-api-cejshe7hxq-de.a.run.app"
EXPECTED_REDIRECT="${NEW_URL}/api/v1/auth/google/callback"
NEW_PROJECT_NUMBER="895523470853"

pass=0; fail=0
ok()   { echo "  [OK]   $1"; pass=$((pass+1)); }
bad()  { echo "  [FAIL] $1"; fail=$((fail+1)); }

echo "=== 1. 服務存活 ==="
health=$(curl -s -m 15 "${NEW_URL}/health")
if [ "$health" = '{"status":"ok"}' ]; then
    ok "/health 回應正常"
else
    bad "/health 異常：$health"
fi

echo "=== 2. DB 連線（app_user 密碼 + app_role 授權）==="
# /readyz 會實際跑 SELECT 1，是唯一能一次驗證密碼與 role 的端點。
# 500 = 連線建不起來（密碼錯或 role 不存在）；503 = 連得上但查詢失敗。
code=$(curl -s -m 20 -o /tmp/readyz.txt -w "%{http_code}" "${NEW_URL}/readyz")
body=$(cat /tmp/readyz.txt 2>/dev/null)
case "$code" in
    200) ok "/readyz 200 — DB 連線正常" ;;
    500) bad "/readyz 500 — 連線建不起來。先跑 fix_db_auth.sh；"
         echo "         若錯誤是 app_role 相關，再跑 backend/scripts/repair_roles_after_migration.sql" ;;
    503) bad "/readyz 503 — 連得上但查詢失敗：$body" ;;
    *)   bad "/readyz 非預期狀態 $code：$body" ;;
esac

echo "=== 3. OAuth redirect_uri ==="
auth_url=$(curl -s -m 15 "${NEW_URL}/api/v1/auth/google/login/mobile")
redirect=$(printf '%s' "$auth_url" | grep -o 'redirect_uri=[^&]*' | cut -d= -f2- \
    | sed 's/%3A/:/g; s/%2F/\//g')
if [ "$redirect" = "$EXPECTED_REDIRECT" ]; then
    ok "redirect_uri 指向新服務"
elif printf '%s' "$redirect" | grep -q 'localhost'; then
    bad "redirect_uri 仍是 localhost 預設值 — GOOGLE_OAUTH_REDIRECT_URI 沒設，請跑 setup_new_project.sh"
else
    bad "redirect_uri 非預期：$redirect"
fi

echo "=== 4. OAuth client 歸屬 ==="
# client_id 開頭是所屬專案編號。目前預期仍在舊專案，白名單要去舊專案加。
client_id=$(printf '%s' "$auth_url" | grep -o 'client_id=[^&]*' | cut -d= -f2-)
client_project=${client_id%%-*}
if [ "$client_project" = "$NEW_PROJECT_NUMBER" ]; then
    ok "OAuth client 已在新專案（$client_project）"
else
    echo "  [注意] OAuth client 仍在舊專案 $client_project —"
    echo "         callback 白名單要去該專案的 Console 加，不是新專案。"
fi

echo "=== 5. 舊服務是否仍在運作 ==="
old_code=$(curl -s -m 15 -o /dev/null -w "%{http_code}" "${OLD_URL}/health")
if [ "$old_code" = "200" ]; then
    echo "  [注意] 舊服務仍活著（HTTP 200）。舊版 App 會繼續連過去而不報錯，"
    echo "         切換完成前先別關；全部驗收通過後再停用，以免問題被掩蓋。"
else
    ok "舊服務已停用（HTTP $old_code）"
fi

echo
echo "通過 $pass 項，失敗 $fail 項。"
[ "$fail" -eq 0 ] || exit 1
