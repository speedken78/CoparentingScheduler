"""Auth helpers for integration tests — bypass Google OAuth."""
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.user_repo import UserRepository
from app.utils.jwt_utils import create_access_token


async def create_test_user_and_token(
    db: AsyncSession,
    display_name: str = "測試使用者",
    role: str = "parent",
) -> tuple[User, str]:
    """Insert a user directly (no Google OAuth) and return (user, access_token)."""
    repo = UserRepository(db)
    uid = uuid4().hex[:6]
    user = await repo.insert({
        "email": f"test_{uid}@test.com",
        "display_name": display_name,
        "role": role,
        "google_sub": f"test_sub_{uuid4().hex}",
    })
    token = create_access_token(str(user.id))
    return user, token
