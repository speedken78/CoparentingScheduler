from sqlalchemy import BigInteger, Column, DateTime, Integer, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class GCalSyncLog(Base):
    __tablename__ = "gcal_sync_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    entity_type = Column(Text, nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    gcal_event_id = Column(Text)
    error_message = Column(Text)
    duration_ms = Column(Integer)
    synced_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
