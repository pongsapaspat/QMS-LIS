from sqlalchemy.orm import Session

from app.domain.exceptions import (
    CatalogNotFoundError,
    OrderNotFoundError,
    PatientNotFoundError,
)
from app.models.base import utc_now
from app.models.order import LabOrder, LabOrderItem
from app.repositories.order import OrderRepository
from app.schemas.order import LabOrderCreate


class OrderService:
    def __init__(self, session: Session, repository: OrderRepository | None = None) -> None:
        self.session = session
        self.repository = repository or OrderRepository(session)

    def create(self, data: LabOrderCreate, *, actor_reference: str) -> LabOrder:
        patient = self.repository.get_patient(data.patient_id)
        if patient is None or not patient.is_active:
            raise PatientNotFoundError("active patient not found")

        tests = self.repository.get_active_tests(data.test_ids)
        if len(tests) != len(data.test_ids):
            raise CatalogNotFoundError("one or more active Lab Tests were not found")

        ordered_at = utc_now()
        order = LabOrder(
            order_number="PENDING",
            patient_id=patient.id,
            priority=data.priority,
            clinical_note=data.clinical_note,
            ordered_at=ordered_at,
            created_by=actor_reference,
        )
        self.repository.add(order)
        order.order_number = f"ORD{ordered_at:%Y%m%d}-{order.id:06d}"
        order.items = [
            LabOrderItem(
                lab_test_id=test.id,
                test_code=test.code,
                test_name_th=test.name_th,
                test_name_en=test.name_en,
                result_type=test.result_type,
                result_unit=test.result_unit,
                price=test.current_price,
            )
            for test in tests
        ]
        try:
            self.session.commit()
            self.session.refresh(order)
        except Exception:
            self.session.rollback()
            raise
        return self.get(order.id)

    def get(self, order_id: int) -> LabOrder:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        return order
