from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entry: AuditLog) -> AuditLog:
        self.session.add(entry)
        self.session.flush()
        return entry

    def list_for_entity(self, entity_type: str, entity_id: int) -> list[AuditLog]:
        statement = (
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        )
        return list(self.session.scalars(statement))
