import uuid
from sqlalchemy import Column, Text, Boolean, Integer, DateTime, ForeignKey, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class HandoverRecord(Base):
    __tablename__ = "handover_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("custody_events.id"), nullable=False)
    action = Column(Text, nullable=False)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    performed_at = Column(DateTime(timezone=True), nullable=False)
    location_lat = Column(Numeric(8, 3))
    location_lng = Column(Numeric(8, 3))
    location_accuracy_m = Column(Integer)
    photo_gcs_path = Column(Text)
    counterparty_confirmed = Column(Boolean, nullable=False, server_default="false")
    counterparty_confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
