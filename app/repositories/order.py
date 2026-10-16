
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder
from app.models.patient import Patient
from app.models.test_catalog import LabTest


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, entity: object) -> None:
        self.session.add(entity)
        self.session.flush()

    def get_order(self, order_id: int) -> LabOrder | None:
        statement = (
            select(LabOrder)
            .options(selectinload(LabOrder.items), selectinload(LabOrder.patient))
            .where(LabOrder.id == order_id)
        )
        return self.session.scalars(statement).first()

    def get_patient(self, patient_id: int) -> Patient | None:
        return self.session.get(Patient, patient_id)

    def get_active_tests(self, test_ids: list[int]) -> list[LabTest]:
        statement = (
            select(LabTest)
            .where(LabTest.id.in_(test_ids), LabTest.is_active.is_(True))
            .order_by(LabTest.code)
        )
        return list(self.session.scalars(statement))
