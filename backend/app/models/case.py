import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base


class FamilyCase(Base):
    __tablename__ = "family_cases"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_name = Column(Text, nullable=False)
    court_case_no = Column(Text)
    custody_type = Column(Text, nullable=False)
    custody_ratio = Column(JSONB)
    timezone = Column(Text, nullable=False, server_default="Asia/Taipei")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))


class CaseMembership(Base):
    __tablename__ = "case_memberships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("family_cases.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    relation = Column(Text, nullable=False)
    permissions = Column(JSONB, nullable=False, server_default='{"read":true,"write":true}')
    invited_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
