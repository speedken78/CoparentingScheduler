import uuid
from sqlalchemy import Boolean, Column, DateTime, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    phone = Column(Text)
    display_name = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    line_user_id = Column(Text, unique=True)
    google_oauth_token_enc = Column(LargeBinary)
    google_sub = Column(Text, unique=True)
    google_refresh_token_enc = Column(LargeBinary)
    gcal_scope_granted = Column(Boolean, nullable=False, default=False, server_default="false")
    last_login_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))
