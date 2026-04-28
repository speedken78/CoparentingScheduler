import uuid
from sqlalchemy import Column, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class CustodyEvent(Base):
    __tablename__ = "custody_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("family_cases.id"), nullable=False)
    child_id = Column(UUID(as_uuid=True), ForeignKey("children.id"))
    custodian_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("custody_rules.id"))
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False, server_default="scheduled")
    handover_location = Column(Text)
    notes = Column(Text)
    gcal_event_id = Column(Text)
    gcal_synced_at = Column(DateTime(timezone=True))
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))
