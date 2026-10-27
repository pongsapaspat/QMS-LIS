from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder, LabOrderItem
from app.models.patient import Patient
from app.models.result import Result
from app.models.specimen import Specimen, SpecimenItem
from app.models.test_catalog import LabTest, QualitativeResultOption, ReferenceRange


class ResultRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_order(self, order_id: int) -> LabOrder | None:
        statement = (
            select(LabOrder)
            .options(selectinload(LabOrder.patient), selectinload(LabOrder.items))
            .where(LabOrder.id == order_id)
        )
        return self.session.scalars(statement).first()

    def order_context(self, order_id: int) -> list[LabOrderItem]:
        statement = (
            select(LabOrderItem)
            .options(
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.reference_ranges),
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.qualitative_options),
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.department),
                selectinload(LabOrderItem.result),
                selectinload(LabOrderItem.order).selectinload(LabOrder.patient),
            )
            .where(LabOrderItem.order_id == order_id)
            .order_by(LabOrderItem.id)
        )
        return list(self.session.scalars(statement))

    def specimen_for_item(self, order_item_id: int) -> Specimen | None:
        statement = (
            select(Specimen).join(SpecimenItem).where(SpecimenItem.order_item_id == order_item_id)
        )
        return self.session.scalars(statement).first()

    def list_worklist(
        self,
        *,
        department_id: int | None,
        status: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[LabOrderItem, Specimen, Result | None]], int]:
        statement = (
            select(LabOrderItem, Specimen, Result)
            .join(SpecimenItem, SpecimenItem.order_item_id == LabOrderItem.id)
            .join(Specimen, Specimen.id == SpecimenItem.specimen_id)
            .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .outerjoin(Result, Result.order_item_id == LabOrderItem.id)
            .options(
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.department),
                selectinload(LabOrderItem.order).selectinload(LabOrder.patient),
            )
            .where(Specimen.status == "RECEIVED")
        )
        if department_id is not None:
            statement = statement.where(LabTest.department_id == department_id)
        if status is not None:
            statement = (
                statement.where(Result.status == status)
                if status != "PENDING"
                else statement.where(or_(Result.id.is_(None), Result.status == "PENDING"))
            )
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabOrder.order_number.ilike(term),
                    Specimen.accession_number.ilike(term),
                    Patient.hn.ilike(term),
                )
            )
        total = self.session.execute(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ).scalar_one()
        statement = (
            statement.order_by(LabOrder.priority.desc(), Specimen.received_at, Specimen.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.execute(statement).all()), total

    def active_ranges(self, test_id: int) -> list[ReferenceRange]:
        return list(
            self.session.scalars(
                select(ReferenceRange)
                .where(ReferenceRange.test_id == test_id, ReferenceRange.is_active.is_(True))
                .order_by(ReferenceRange.priority.desc(), ReferenceRange.id)
            )
        )

    def active_options(self, test_id: int) -> list[QualitativeResultOption]:
        return list(
            self.session.scalars(
                select(QualitativeResultOption).where(
                    QualitativeResultOption.test_id == test_id,
                    QualitativeResultOption.is_active.is_(True),
                )
            )
        )
