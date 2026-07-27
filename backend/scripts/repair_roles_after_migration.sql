-- 移轉到新 GCP 專案後，修復 app_role / app_user 的角色與授權。
--
-- 為什麼需要：PostgreSQL 的 role 屬於 cluster 層級，不包含在單一 database 的
-- dump 裡。用 pg_dump/pg_restore 搬 database 時，role 定義、成員關係與 GRANT
-- 都不會跟著過來，必須在新 instance 重放一次。
--
-- 本檔重放 alembic 009_app_role.py，外加 011/012/013 針對個別資料表的 GRANT。
-- 全部冪等，可重複執行。
--
-- 執行（Cloud Shell，以 postgres 連新 instance）：
--   gcloud sql connect coparenting-db --user=postgres --database=coparenting
--   \i repair_roles_after_migration.sql
--
-- 沒有 psql 時：本檔（去掉 \set 那行）可用 asyncpg 的 Connection.execute()
-- 一次送出——simple query protocol 支援多敘述與 DO $$ 區塊。
-- 注意 asyncpg.connect() 不能直接吃這種 DSN：netloc 的 localhost 會蓋掉
-- ?host= 查詢參數而退回 TCP 127.0.0.1:5432，必須把 host 拆成 kwarg 傳入。
--
-- 注意：本檔不設定 app_user 密碼。密碼請用 fix_db_auth.sh 處理，
-- 以確保 Cloud SQL 與 Secret Manager 兩邊一致。

\set ON_ERROR_STOP on

-- === 1. 角色本身 ===

-- app_role：有 BYPASSRLS 但無 DDL、無登入能力。
-- NOINHERIT 是關鍵——app_user 不會自動繼承這些權限，
-- 必須明確 SET ROLE app_role 才生效（見 backend/app/database.py:27）。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
        CREATE ROLE app_role WITH
            NOLOGIN
            NOINHERIT
            BYPASSRLS
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE;
    END IF;
END
$$;

-- 角色若已存在但屬性被移轉工具改掉，強制校正回來。
--
-- 實測（2026-07-27）：移轉後 app_role 變成 rolbypassrls=f、rolcanlogin=t、
-- rolinherit=t，全部偏離原設計，必須改回來。
--
-- 必須拆成多道敘述，不能合寫成一行 ALTER ROLE ... NOSUPERUSER ...：
-- Cloud SQL 的 postgres 是 cloudsqlsuperuser 而非真 superuser，只要敘述裡
-- 出現 SUPERUSER/NOSUPERUSER 就會整道被擋：
--   InsufficientPrivilegeError: permission denied to alter role
--   DETAIL: Only roles with the SUPERUSER attribute may change the SUPERUSER attribute.
-- 拆開後 BYPASSRLS 本身是設得起來的。NOSUPERUSER 則省略——Cloud SQL 上
-- 本來就無法建立 superuser，不需要校正。
ALTER ROLE app_role NOLOGIN;
ALTER ROLE app_role NOINHERIT;
ALTER ROLE app_role BYPASSRLS;

-- app_user：API runtime 實際登入用的帳號，本身不具 BYPASSRLS。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user WITH
            LOGIN
            NOINHERIT
            PASSWORD 'PLACEHOLDER_SET_BY_fix_db_auth_sh'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE;
    END IF;
END
$$;

ALTER ROLE app_user LOGIN;
ALTER ROLE app_user NOINHERIT;

-- 成員關係：沒有這行，SET ROLE app_role 會失敗
-- （permission denied to set role "app_role"）。
GRANT app_role TO app_user;

-- === 2. Schema 與資料表授權 ===

GRANT USAGE ON SCHEMA public TO app_role;
GRANT USAGE ON SCHEMA public TO app_user;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_role;

-- 日後新建的資料表也自動授權（migration 009 的 ALTER DEFAULT PRIVILEGES）。
-- 注意：DEFAULT PRIVILEGES 只對「執行這道指令的角色」之後建立的物件生效，
-- 所以要以跑 migration 的那個使用者（postgres）身分執行本檔。
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_role;

-- 後續 migration 對個別資料表的 GRANT（011 / 012 / 013）。
-- 上面的 ALL TABLES 已涵蓋，這裡明列是為了對照 migration 檔、避免日後漏掉。
GRANT SELECT, INSERT, UPDATE, DELETE ON revocation_proposals TO app_role;  -- 011
GRANT SELECT, INSERT ON gcal_sync_log TO app_role;                          -- 012
GRANT SELECT, INSERT ON reports TO app_role;                                -- 013

-- === 3. audit_log 的不可竄改性 ===
-- 稽核軌跡只能新增不能改動，這道 REVOKE 必須排在 ALL TABLES 授權之後，
-- 否則會被上面的 GRANT 蓋掉。
REVOKE UPDATE, DELETE ON audit_log FROM app_role;

-- === 4. 驗證 ===

-- 預期：app_role  bypassrls=t  super=f  login=f
--       app_user  bypassrls=f  super=f  login=t
SELECT rolname, rolbypassrls, rolsuper, rolcanlogin, rolinherit
FROM pg_roles
WHERE rolname IN ('app_role', 'app_user')
ORDER BY rolname;

-- 預期：回傳一列，證明 app_user 是 app_role 的成員
SELECT r.rolname AS role, m.rolname AS member
FROM pg_auth_members am
JOIN pg_roles r ON r.oid = am.roleid
JOIN pg_roles m ON m.oid = am.member
WHERE r.rolname = 'app_role';

-- 預期：audit_log 只有 SELECT 與 INSERT，沒有 UPDATE / DELETE
SELECT table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee = 'app_role' AND table_name = 'audit_log'
ORDER BY privilege_type;
