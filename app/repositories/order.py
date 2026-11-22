from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder, LabOrderItem, OrderStatus
from app.models.outlab import OutlabCase, OutlabDocument
from app.models.patient import Patient
from app.models.result import Result
from app.models.specimen import Specimen
from app.models.test_catalog import LaboratoryDepartment, LabTest


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

    def list_orders(
        self, *, search: str, status: OrderStatus | None, start: datetime | None,
        end: datetime | None, include_older_open: bool, offset: int, limit: int,
    ) -> tuple[list[LabOrder], int]:
        query = select(LabOrder).join(LabOrder.patient)
        if include_older_open and start is not None and end is not None:
            query = query.where(or_(
                and_(LabOrder.ordered_at >= start, LabOrder.ordered_at < end),
                and_(LabOrder.ordered_at < start,
                     LabOrder.status.not_in([OrderStatus.RELEASED, OrderStatus.CANCELLED])),
            ))
        else:
            if start is not None:
                query = query.where(LabOrder.ordered_at >= start)
            if end is not None:
                query = query.where(LabOrder.ordered_at < end)
        if status is not None:
            query = query.where(LabOrder.status == status)
        for word in search.split():
            query = query.where(or_(*(
                field.icontains(word, autoescape=True) for field in (
                    LabOrder.order_number, Patient.hn, Patient.first_name_th,
                    Patient.last_name_th, Patient.first_name_en, Patient.last_name_en,
                )
            )))
        count = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        orders = self.session.scalars(
            query.options(
                selectinload(LabOrder.patient),
                selectinload(LabOrder.items).selectinload(LabOrderItem.lab_test)
                .selectinload(LabTest.specimen_type),
                selectinload(LabOrder.items).selectinload(LabOrderItem.result)
                .load_only(Result.status),
                selectinload(LabOrder.items).selectinload(LabOrderItem.outlab)
                .selectinload(OutlabCase.documents).load_only(OutlabDocument.id),
            ).order_by(LabOrder.ordered_at.desc(), LabOrder.id.desc()).offset(offset).limit(limit)
        )
        return list(orders), count

    def current_specimens(self, order_ids: list[int]) -> list[Specimen]:
        if not order_ids:
            return []
        return list(self.session.scalars(
            select(Specimen)
            .options(selectinload(Specimen.items), selectinload(Specimen.specimen_type))
            .where(Specimen.order_id.in_(order_ids), Specimen.is_current.is_(True))
        ))

    def get_patient(self, patient_id: int) -> Patient | None:
        return self.session.get(Patient, patient_id)

    def get_active_tests(self, test_ids: list[int]) -> list[LabTest]:
        statement = (
            select(LabTest)
            .join(LaboratoryDepartment, LaboratoryDepartment.id == LabTest.department_id)
            .where(
                LabTest.id.in_(test_ids),
                LabTest.is_active.is_(True),
                LaboratoryDepartment.is_active.is_(True),
            )
            .order_by(LabTest.code)
        )
        return list(self.session.scalars(statement))
