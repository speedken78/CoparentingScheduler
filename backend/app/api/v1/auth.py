from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import jwt

from app.config import settings
from app.database import get_db
from app.deps import get_current_user
from app.repositories.user_repo import UserRepository
from app.schemas.auth import AccessTokenResponse, GoogleLoginResponse, RefreshRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services import audit_service
from app.utils.jwt_utils import create_access_token, create_refresh_token, decode_token
from app.utils.kms import encrypt as encrypt_with_kms

router = APIRouter()


def _build_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uris": [settings.GOOGLE_OAUTH_REDIRECT_URI],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "https://www.googleapis.com/auth/calendar.events",
        ],
    )


@router.get("/google/login", response_model=GoogleLoginResponse)
async def google_login():
    flow = _build_flow()
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    return {"auth_url": auth_url}


@router.get("/google/callback")
async def google_callback(code: str, state: str = "", db: AsyncSession = Depends(get_db)):
    """
    OAuth callback。
    若 state 包含 "platform=mobile" 則 redirect 到 deep link（App 接收 token）。
    否則回傳 JSON（API 測試用）。
    """
    import json
    import urllib.parse
    from fastapi.responses import RedirectResponse
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests

    flow = _build_flow()
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to exchange code: {exc}")

    credentials = flow.credentials

    try:
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            google_requests.Request(),
            settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid ID token: {exc}")

    google_sub = id_info["sub"]
    email = id_info["email"]
    display_name = id_info.get("name", email.split("@")[0])

    refresh_token_enc: bytes | None = None
    if credentials.refresh_token:
        refresh_token_enc = encrypt_with_kms(credentials.refresh_token.encode())

    gcal_granted = bool(
        credentials.scopes
        and "https://www.googleapis.com/auth/calendar.events" in credentials.scopes
    )

    user = await UserRepository(db).upsert_by_google_sub(
        google_sub=google_sub,
        email=email,
        display_name=display_name,
        refresh_token_enc=refresh_token_enc,
        gcal_scope_granted=gcal_granted,
    )

    await audit_service.log(
        db,
        case_id=None,
        actor_id=user.id,
        action="user_login",
        entity_type="user",
        entity_id=user.id,
        after_state={"method": "google_oauth"},
        triggered_by="human",
    )

    await db.commit()

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))

    # Mobile App：redirect 到 deep link
    if "platform=mobile" in state:
        user_json = urllib.parse.quote(json.dumps({
            "id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
            "gcal_scope_granted": user.gcal_scope_granted,
        }))
        redirect_url = (
            f"coparenting://auth"
            f"?access_token={access_token}"
            f"&refresh_token={refresh_token}"
            f"&user={user_json}"
        )
        return RedirectResponse(url=redirect_url)

    # Web / API 測試：回傳 JSON
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": UserResponse.model_validate(user),
    }


@router.get("/google/login/mobile", response_model=GoogleLoginResponse)
async def google_login_mobile():
    """App 專用登入 URL，state 內含 platform=mobile 標記。"""
    import urllib.parse
    flow = _build_flow()
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    # 在 state 後方附加 platform 標記（Google 會原樣回傳 state）
    mobile_state = state + ":platform=mobile"
    auth_url_with_state = auth_url.replace(
        f"state={urllib.parse.quote(state)}",
        f"state={urllib.parse.quote(mobile_state)}",
    )
    return {"auth_url": auth_url_with_state}


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_token(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    access_token = create_access_token(payload["sub"])
    return {"access_token": access_token}


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
