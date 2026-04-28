import uuid
from sqlalchemy import Column, Text, Date, Time, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class CustodyRule(Base):
    __tablename__ = "custody_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("family_cases.id"), nullable=False)
    child_id = Column(UUID(as_uuid=True), ForeignKey("children.id"))
    custodian_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rule_type = Column(Text, nullable=False)
    rrule = Column(Text, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_until = Column(Date)
    priority = Column(Integer, nullable=False, server_default="100")
    source = Column(Text, nullable=False)
    source_document = Column(Text)
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    revoked_at = Column(DateTime(timezone=True))
    revoked_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    revoked_reason = Column(Text)
