#!/bin/bash
# Runs on first PostgreSQL startup (empty volume). Creates app_role and app_user
# with the correct password from the APP_DB_PASSWORD environment variable.
set -e

APP_DB_PASSWORD="${APP_DB_PASSWORD:-changeme}"

psql -v ON_ERROR_STOP=1 --username "postgres" --dbname "coparenting" <<EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role') THEN
            CREATE ROLE app_role WITH
                NOLOGIN NOINHERIT BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
        END IF;
    END
    \$\$;

    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            CREATE ROLE app_user WITH
                LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
                PASSWORD '${APP_DB_PASSWORD}';
        ELSE
            ALTER ROLE app_user PASSWORD '${APP_DB_PASSWORD}';
        END IF;
    END
    \$\$;

    GRANT app_role TO app_user;
EOSQL
