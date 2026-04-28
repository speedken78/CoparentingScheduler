from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

# Superuser engine used only by alembic (env.py uses DATABASE_URL directly)
# API runtime uses APP_DATABASE_URL (app_user role — no DDL, gains BYPASSRLS via SET ROLE)
# NullPool: each session gets a fresh connection — avoids asyncio event-loop binding issues
# and works correctly with asyncpg. A connection pool can be re-added when needed.
engine = create_async_engine(
    settings.APP_DATABASE_URL,
    poolclass=NullPool,
    echo=settings.DEBUG,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        # Elevate to app_role so this session has BYPASSRLS + DML but still no DDL
        await session.execute(text("SET ROLE app_role"))
        yield session
