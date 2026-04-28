import uuid
from sqlalchemy import Column, Text, BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    case_id = Column(UUID(as_uuid=True), nullable=False)
    actor_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    before_state = Column(JSONB)
    after_state = Column(JSONB)
    triggered_by = Column(Text, nullable=False, server_default="human")
    agent_session_id = Column(UUID(as_uuid=True), ForeignKey("agent_sessions.id"))
    ip_address = Column(INET)
    user_agent = Column(Text)
    device_id = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    prev_hash = Column(Text)
    row_hash = Column(Text, nullable=False)


class AuditAnchor(Base):
    __tablename__ = "audit_anchors"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    anchored_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_audit_id = Column(BigInteger, nullable=False)
    last_row_hash = Column(Text, nullable=False)
    anchor_target = Column(Text, nullable=False)
    anchor_proof = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
