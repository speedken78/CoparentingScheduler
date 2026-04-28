from pydantic import BaseModel
from app.schemas.user import UserResponse


class GoogleLoginResponse(BaseModel):
    auth_url: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str
