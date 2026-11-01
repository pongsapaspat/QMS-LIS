from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.order import LabOrder, LabOrderItem
from app.models.patient import Patient
from app.models.result import Result, ResultStatus
from app.models.specimen import Specimen, SpecimenItem
from app.models.test_catalog import LabTest, QualitativeResultOption, ReferenceRange


class ResultRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_order(self, order_id: int) -> LabOrder | None:
        statement = (
            select(LabOrder)
            .options(
                selectinload(LabOrder.patient),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.result)
                .selectinload(Result.specimen),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.result)
                .selectinload(Result.revisions),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.lab_test)
                .selectinload(LabTest.department),
            )
            .where(LabOrder.id == order_id)
        )
        return self.session.scalars(statement).first()

    def get_result(self, result_id: int) -> Result | None:
        statement = (
            select(Result)
            .options(
                selectinload(Result.specimen),
                selectinload(Result.revisions),
                selectinload(Result.order_item)
                .selectinload(LabOrderItem.order)
                .selectinload(LabOrder.patient),
                selectinload(Result.order_item)
                .selectinload(LabOrderItem.lab_test)
                .selectinload(LabTest.department),
            )
            .where(Result.id == result_id)
        )
        return self.session.scalars(statement).first()

    def order_context(self, order_id: int) -> list[LabOrderItem]:
        statement = (
            select(LabOrderItem)
            .options(
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.reference_ranges),
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.qualitative_options),
                selectinload(LabOrderItem.lab_test).selectinload(LabTest.department),
                selectinload(LabOrderItem.result).selectinload(Result.specimen),
                selectinload(LabOrderItem.result).selectinload(Result.revisions),
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

    def list_verification_queue(
        self,
        *,
        department_id: int | None,
        priority: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Result], int]:
        statement = (
            select(Result)
            .join(LabOrderItem, LabOrderItem.id == Result.order_item_id)
            .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .join(Specimen, Specimen.id == Result.specimen_id)
            .options(
                selectinload(Result.specimen),
                selectinload(Result.revisions),
                selectinload(Result.order_item)
                .selectinload(LabOrderItem.order)
                .selectinload(LabOrder.patient),
                selectinload(Result.order_item)
                .selectinload(LabOrderItem.lab_test)
                .selectinload(LabTest.department),
            )
            .where(
                Result.status.in_(
                    [ResultStatus.COMPLETED, ResultStatus.VERIFICATION_REJECTED]
                ),
                LabOrder.status != "CANCELLED",
                Specimen.status == "RECEIVED",
            )
        )
        if department_id is not None:
            statement = statement.where(LabTest.department_id == department_id)
        if priority is not None:
            statement = statement.where(LabOrder.priority == priority)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabOrder.order_number.ilike(term),
                    Specimen.accession_number.ilike(term),
                    Patient.hn.ilike(term),
                    LabOrderItem.test_code.ilike(term),
                    Patient.first_name_th.ilike(term),
                    Patient.last_name_th.ilike(term),
                    Patient.first_name_en.ilike(term),
                    Patient.last_name_en.ilike(term),
                )
            )
        total = self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        statement = (
            statement.order_by(
                LabOrder.priority.desc(), Result.entered_at, Result.id
            )
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement)), total

    def list_release_queue(
        self,
        *,
        priority: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[LabOrder], int]:
        statement = (
            select(LabOrder)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .options(
                selectinload(LabOrder.patient),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.lab_test)
                .selectinload(LabTest.department),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.result)
                .selectinload(Result.specimen),
            )
            .where(LabOrder.status == "RESULTS_VERIFIED")
        )
        if priority is not None:
            statement = statement.where(LabOrder.priority == priority)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabOrder.order_number.ilike(term),
                    Patient.hn.ilike(term),
                    Patient.first_name_th.ilike(term),
                    Patient.last_name_th.ilike(term),
                    Patient.first_name_en.ilike(term),
                    Patient.last_name_en.ilike(term),
                )
            )
        total = self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        statement = (
            statement.order_by(LabOrder.priority.desc(), LabOrder.verified_at, LabOrder.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement)), total

    def list_released_orders(
        self,
        *,
        search: str | None,
        released_from: datetime | None,
        released_before: datetime | None,
        offset: int,
        limit: int,
    ) -> tuple[list[LabOrder], int]:
        statement = (
            select(LabOrder)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .options(
                selectinload(LabOrder.patient),
                selectinload(LabOrder.items)
                .selectinload(LabOrderItem.result)
                .selectinload(Result.specimen),
            )
            .where(LabOrder.status == "RELEASED")
        )
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabOrder.order_number.ilike(term),
                    Patient.hn.ilike(term),
                    Patient.first_name_th.ilike(term),
                    Patient.last_name_th.ilike(term),
                    Patient.first_name_en.ilike(term),
                    Patient.last_name_en.ilike(term),
                    LabOrder.items.any(
                        LabOrderItem.result.has(
                            Result.specimen.has(Specimen.accession_number.ilike(term))
                        )
                    ),
                )
            )
        if released_from is not None:
            statement = statement.where(LabOrder.released_at >= released_from)
        if released_before is not None:
            statement = statement.where(LabOrder.released_at < released_before)
        total = self.session.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        statement = (
            statement.order_by(LabOrder.released_at.desc(), LabOrder.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement)), total

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
