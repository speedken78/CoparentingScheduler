from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 環境
    ENV: str = "development"
    # Superuser URL for alembic migrations only
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/coparenting"
    # app_user URL for API runtime (BYPASSRLS via app_role, no DDL)
    APP_DATABASE_URL: str = "postgresql+asyncpg://app_user:changeme@localhost:5432/coparenting"
    APP_DB_PASSWORD: str = "changeme"

    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-haiku-4-5"

    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    LINE_CHANNEL_ACCESS_TOKEN: str = ""
    LINE_CHANNEL_SECRET: str = ""

    GCS_BUCKET_AUDIT: str = "coparenting-audit-anchors"
    GCS_BUCKET_REPORTS: str = "coparenting-reports"

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7

    # KMS: "local" uses AES-256-GCM with LOCAL_ENCRYPT_KEY; "gcp" uses GCP KMS
    KMS_MODE: str = "local"
    LOCAL_ENCRYPT_KEY: str = ""  # 32 bytes base64-encoded
    KMS_KEY_NAME: str = ""

    PDF_STORAGE_MODE: str = "local"

    JOB_SECRET_TOKEN: str = "change_me_to_random_32_chars"

    DEBUG: bool = False
    ENVIRONMENT: str = "development"


settings = Settings()
