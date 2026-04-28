import uuid
from sqlalchemy import Column, Text, Date, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class RevocationProposal(Base):
    __tablename__ = "revocation_proposals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("family_cases.id"), nullable=False)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("custody_rules.id"))
    rule_hint = Column(Text, nullable=False)
    revocation_reason = Column(Text, nullable=False)
    effective_from = Column(Date, nullable=False)
    proposed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    agent_session_id = Column(UUID(as_uuid=True), ForeignKey("agent_sessions.id"))
    status = Column(Text, nullable=False, server_default="pending")
    confirmed_at = Column(DateTime(timezone=True))
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW() + INTERVAL '7 days'"))
