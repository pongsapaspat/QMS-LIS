from sqlalchemy.orm import Session

from app.domain.exceptions import (
    CatalogNotFoundError,
    OrderNotFoundError,
    PatientNotFoundError,
)
from app.domain.panels import panel_definitions
from app.models.base import utc_now
from app.models.order import LabOrder, LabOrderItem
from app.models.outlab import OutlabCase
from app.repositories.order import OrderRepository
from app.schemas.order import LabOrderCreate
from app.services.package import PackageService


class OrderService:
    def __init__(self, session: Session, repository: OrderRepository | None = None) -> None:
        self.session = session
        self.repository = repository or OrderRepository(session)

    def create(self, data: LabOrderCreate, *, actor_reference: str) -> LabOrder:
        patient = self.repository.get_patient(data.patient_id)
        if patient is None or not patient.is_active:
            raise PatientNotFoundError("active patient not found")

        packages = [PackageService(self.session).get(package_id) for package_id in data.package_ids]
        if any(not package.available for package in packages):
            raise CatalogNotFoundError('One or more packages are unavailable')
        selected_ids = set(data.test_ids)
        for package in packages:
            selected_ids.update(test.id for test in package.tests)
        tests = self.repository.get_active_tests(list(selected_ids))
        if len(tests) != len(selected_ids):
            raise CatalogNotFoundError("one or more active Lab Tests were not found")

        ordered_at = utc_now()
        order = LabOrder(
            order_number="PENDING",
            patient_id=patient.id,
            priority=data.priority,
            clinical_note=data.clinical_note,
            ordered_at=ordered_at,
            created_by=actor_reference,
            package_snapshots=[{
                'id': p.id, 'code': p.code, 'name': p.name, 'price': str(p.price),
                'test_ids': [test.id for test in p.tests],
                'tests': [{'id': test.id, 'code': test.code, 'name': test.name_en}
                          for test in p.tests],
            } for p in packages] or None,
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
                parameter_definitions=panel_definitions(test.result_type) or None,
                price=test.current_price,
                is_outlab=test.is_outlab,
                outlab=OutlabCase(lab_name=test.outlab_lab_name) if test.is_outlab else None,
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
