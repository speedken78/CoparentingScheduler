import uuid
from sqlalchemy import Column, Text, Date, BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class Report(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("family_cases.id"), nullable=False)
    report_type = Column(Text, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    generated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    pdf_gcs_path = Column(Text, nullable=False)
    pdf_sha256 = Column(Text, nullable=False)
    last_audit_id = Column(BigInteger, nullable=False)
    last_audit_hash = Column(Text, nullable=False)
    anchor_id = Column(BigInteger, ForeignKey("audit_anchors.id"))
