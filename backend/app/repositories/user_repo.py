from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: str | UUID) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.email == email, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_by_google_sub(self, google_sub: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.google_sub == google_sub, User.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def insert(self, data: dict) -> User:
        user = User(**data)
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def upsert_by_google_sub(
        self,
        google_sub: str,
        email: str,
        display_name: str,
        refresh_token_enc: Optional[bytes],
        gcal_scope_granted: bool,
    ) -> User:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        user = await self.get_by_google_sub(google_sub)
        if user is None:
            # New user
            data: dict = {
                "email": email,
                "display_name": display_name,
                "role": "parent",
                "google_sub": google_sub,
                "gcal_scope_granted": gcal_scope_granted,
                "last_login_at": now,
            }
            if refresh_token_enc is not None:
                data["google_refresh_token_enc"] = refresh_token_enc
            user = await self.insert(data)
        else:
            # Existing user — update fields
            user.email = email
            user.display_name = display_name
            user.gcal_scope_granted = gcal_scope_granted
            user.last_login_at = now
            if refresh_token_enc is not None:
                user.google_refresh_token_enc = refresh_token_enc
            await self.db.flush()
            await self.db.refresh(user)
        return user
