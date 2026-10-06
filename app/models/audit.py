from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, utc_now


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False, index=True
    )


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def prevent_audit_mutation(mapper: object, connection: object, target: AuditLog) -> None:
    raise RuntimeError("audit log entries are immutable")
