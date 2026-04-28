from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import jwt

from app.database import get_db
from app.repositories.user_repo import UserRepository
from app.utils.jwt_utils import decode_token

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User
    token = credentials.credentials
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user_id = payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Set RLS context for this request's transaction.
    # user_id is a validated UUID string so f-string interpolation is safe here.
    await db.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))

    user = await UserRepository(db).get_by_id(user_id)
    if not user or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_request_context(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }
