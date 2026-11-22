from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.order import LabOrder, LabOrderItem, OrderStatus
from app.models.patient import Patient
from app.models.result import Result, ResultStatus
from app.models.specimen import Specimen, SpecimenItem, SpecimenStatus
from app.models.test_catalog import LaboratoryDepartment, LabTest, SpecimenType
from app.schemas.worklist import WorklistDiagnostics


@dataclass(frozen=True)
class WorklistRecord:
    task_type: str
    task_status: str
    priority: str
    order_id: int
    order_number: str
    patient_id: int
    patient_hn: str
    patient_display_name: str
    order_item_id: int | None
    accession_number: str | None
    specimen_id: int | None
    specimen_type: str | None
    test_code: str | None
    test_name: str | None
    department_id: int | None
    department_code: str | None
    department_name: str | None
    current_order_status: str
    current_specimen_status: str | None
    current_result_status: str | None
    created_at: datetime
    tat_minutes: int | None
    source_actor: str | None = None


class WorklistRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _patient_name(patient: Patient) -> str:
        return patient.display_name

    @staticmethod
    def _search_conditions(
        search: str, *extra: ColumnElement[bool]
    ) -> tuple[ColumnElement[bool], ...]:
        term = f"%{search.strip()}%"
        return (
            LabOrder.order_number.ilike(term),
            Patient.hn.ilike(term),
            Patient.first_name_th.ilike(term),
            Patient.last_name_th.ilike(term),
            Patient.first_name_en.ilike(term),
            Patient.last_name_en.ilike(term),
            (
                func.coalesce(Patient.first_name_th, "")
                + " "
                + func.coalesce(Patient.last_name_th, "")
            ).ilike(term),
            (
                func.coalesce(Patient.first_name_en, "")
                + " "
                + func.coalesce(Patient.last_name_en, "")
            ).ilike(term),
            *extra,
        )

    def list_records(
        self,
        *,
        task_types: set[str],
        department_id: int | None,
        priority: str | None,
        search: str | None,
    ) -> list[WorklistRecord]:
        records: list[WorklistRecord] = []
        if "ORDER_PENDING_COLLECTION" in task_types:
            records.extend(
                self._pending_collection(
                    department_id=department_id, priority=priority, search=search
                )
            )
        if "SPECIMEN_PENDING_RECEIVING" in task_types:
            records.extend(
                self._pending_receiving(
                    department_id=department_id, priority=priority, search=search
                )
            )
        result_types = task_types & {
            "RESULT_PENDING_ENTRY",
            "RESULT_IN_PROGRESS",
            "RESULT_CORRECTION_REQUIRED",
        }
        if result_types:
            records.extend(
                self._pending_results(
                    task_types=result_types,
                    department_id=department_id,
                    priority=priority,
                    search=search,
                )
            )
        return records

    def _pending_collection(
        self, *, department_id: int | None, priority: str | None, search: str | None
    ) -> list[WorklistRecord]:
        specimen_exists = exists(
            select(Specimen.id).join(SpecimenItem).where(
                Specimen.order_id == LabOrder.id,
                SpecimenItem.order_item_id == LabOrderItem.id,
                Specimen.is_current.is_(True),
                Specimen.status != SpecimenStatus.REJECTED,
            )
        )
        rejected_exists = exists(select(Specimen.id).join(SpecimenItem).where(
            Specimen.order_id == LabOrder.id, SpecimenItem.order_item_id == LabOrderItem.id,
            Specimen.is_current.is_(True), Specimen.status == SpecimenStatus.REJECTED,
        ))
        statement = (
            select(
                LabOrder,
                Patient,
                SpecimenType,
                func.min(LabTest.tat_minutes),
                func.count(func.distinct(LabTest.department_id)),
                func.min(LabTest.department_id),
                func.min(LaboratoryDepartment.code),
                func.min(LaboratoryDepartment.name_en),
                func.max(case((rejected_exists, 1), else_=0)),
            )
            .join(Patient, Patient.id == LabOrder.patient_id)
            .join(LabOrderItem, LabOrderItem.order_id == LabOrder.id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .join(SpecimenType, SpecimenType.id == LabTest.specimen_type_id)
            .join(LaboratoryDepartment, LaboratoryDepartment.id == LabTest.department_id)
            .where(LabOrder.status != OrderStatus.CANCELLED, ~specimen_exists)
        )
        if department_id is not None:
            statement = statement.where(LabTest.department_id == department_id)
        if priority is not None:
            statement = statement.where(LabOrder.priority == priority)
        if search:
            statement = statement.where(
                or_(*self._search_conditions(search, LabTest.code.ilike(f"%{search.strip()}%")))
            )
        statement = statement.group_by(LabOrder.id, Patient.id, SpecimenType.id)
        records = []
        # Explicit row shape for this aggregate query, without deprecated tuple filters.
        rows = cast(
            Iterable[tuple[
                LabOrder, Patient, SpecimenType, int, int, int, str, str, int,
            ]],
            self.session.execute(statement),
        )
        for (
            order,
            patient,
            specimen_type,
            tat,
            department_count,
            dept_id,
            dept_code,
            dept_name,
            recollection_required,
        ) in rows:
            records.append(
                WorklistRecord(
                    task_type="ORDER_PENDING_COLLECTION",
                    task_status="PENDING",
                    priority=order.priority,
                    order_id=order.id,
                    order_number=order.order_number,
                    patient_id=patient.id,
                    patient_hn=patient.hn,
                    patient_display_name=self._patient_name(patient),
                    order_item_id=None,
                    accession_number=None,
                    specimen_id=None,
                    specimen_type=specimen_type.name_en,
                    test_code=None,
                    test_name=None,
                    department_id=dept_id if department_count == 1 else None,
                    department_code=dept_code if department_count == 1 else None,
                    department_name=dept_name if department_count == 1 else None,
                    current_order_status=order.status,
                    current_specimen_status="REJECTED" if recollection_required else None,
                    current_result_status=None,
                    created_at=order.ordered_at,
                    tat_minutes=tat,
                )
            )
        return records

    def _pending_receiving(
        self, *, department_id: int | None, priority: str | None, search: str | None
    ) -> list[WorklistRecord]:
        statement = (
            select(
                Specimen,
                LabOrder,
                Patient,
                func.min(LabTest.tat_minutes),
                func.count(func.distinct(LabTest.department_id)),
                func.min(LabTest.department_id),
                func.min(LaboratoryDepartment.code),
                func.min(LaboratoryDepartment.name_en),
            )
            .join(LabOrder, LabOrder.id == Specimen.order_id)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .join(SpecimenItem, SpecimenItem.specimen_id == Specimen.id)
            .join(LabOrderItem, LabOrderItem.id == SpecimenItem.order_item_id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .join(LaboratoryDepartment, LaboratoryDepartment.id == LabTest.department_id)
            .where(
                Specimen.status == SpecimenStatus.COLLECTED,
                Specimen.is_current.is_(True),
                LabOrder.status != OrderStatus.CANCELLED,
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
                    *self._search_conditions(search, LabTest.code.ilike(term)),
                    Specimen.accession_number.ilike(term),
                )
            )
        statement = statement.group_by(Specimen.id, LabOrder.id, Patient.id)
        records = []
        rows = self.session.execute(statement)
        for (
            specimen,
            order,
            patient,
            tat,
            department_count,
            dept_id,
            dept_code,
            dept_name,
        ) in rows:
            records.append(
                WorklistRecord(
                    task_type="SPECIMEN_PENDING_RECEIVING",
                    task_status="PENDING",
                    priority=order.priority,
                    order_id=order.id,
                    order_number=order.order_number,
                    patient_id=patient.id,
                    patient_hn=patient.hn,
                    patient_display_name=self._patient_name(patient),
                    order_item_id=None,
                    accession_number=specimen.accession_number,
                    specimen_id=specimen.id,
                    specimen_type=specimen.specimen_type_name_en,
                    test_code=None,
                    test_name=None,
                    department_id=dept_id if department_count == 1 else None,
                    department_code=dept_code if department_count == 1 else None,
                    department_name=dept_name if department_count == 1 else None,
                    current_order_status=order.status,
                    current_specimen_status=specimen.status,
                    current_result_status=None,
                    created_at=specimen.collected_at,
                    tat_minutes=tat,
                    source_actor=specimen.collected_by,
                )
            )
        return records

    def _pending_results(
        self,
        *,
        task_types: set[str],
        department_id: int | None,
        priority: str | None,
        search: str | None,
    ) -> list[WorklistRecord]:
        statement = (
            select(
                LabOrderItem,
                LabOrder,
                Patient,
                Specimen,
                LabTest,
                LaboratoryDepartment,
                Result,
            )
            .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
            .join(Patient, Patient.id == LabOrder.patient_id)
            .join(SpecimenItem, SpecimenItem.order_item_id == LabOrderItem.id)
            .join(Specimen, Specimen.id == SpecimenItem.specimen_id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .join(LaboratoryDepartment, LaboratoryDepartment.id == LabTest.department_id)
            .outerjoin(Result, Result.order_item_id == LabOrderItem.id)
            .where(
                Specimen.status == SpecimenStatus.RECEIVED,
                Specimen.is_current.is_(True),
                LabOrder.status != OrderStatus.CANCELLED,
                LabOrderItem.is_outlab.is_(False),
            )
        )
        result_conditions = []
        if "RESULT_PENDING_ENTRY" in task_types:
            result_conditions.append(
                or_(Result.id.is_(None), Result.status == ResultStatus.PENDING)
            )
        if "RESULT_IN_PROGRESS" in task_types:
            result_conditions.append(Result.status == ResultStatus.IN_PROGRESS)
        if "RESULT_CORRECTION_REQUIRED" in task_types:
            result_conditions.append(
                Result.status.in_(
                    [ResultStatus.VERIFICATION_REJECTED, ResultStatus.AMENDMENT_REQUESTED]
                )
            )
        statement = statement.where(or_(*result_conditions))
        if department_id is not None:
            statement = statement.where(LabTest.department_id == department_id)
        if priority is not None:
            statement = statement.where(LabOrder.priority == priority)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    *self._search_conditions(search, LabTest.code.ilike(term)),
                    Specimen.accession_number.ilike(term),
                )
            )
        records = []
        for item, order, patient, specimen, lab_test, department, result in self.session.execute(
            statement
        ):
            in_progress = result is not None and result.status == ResultStatus.IN_PROGRESS
            correction_required = (
                result is not None
                and result.status
                in {ResultStatus.VERIFICATION_REJECTED, ResultStatus.AMENDMENT_REQUESTED}
            )
            records.append(
                WorklistRecord(
                    task_type=(
                        "RESULT_CORRECTION_REQUIRED"
                        if correction_required
                        else "RESULT_IN_PROGRESS"
                        if in_progress
                        else "RESULT_PENDING_ENTRY"
                    ),
                    task_status=(
                        "CORRECTION_REQUIRED"
                        if correction_required
                        else "IN_PROGRESS"
                        if in_progress
                        else "PENDING"
                    ),
                    priority=order.priority,
                    order_id=order.id,
                    order_number=order.order_number,
                    patient_id=patient.id,
                    patient_hn=patient.hn,
                    patient_display_name=self._patient_name(patient),
                    order_item_id=item.id,
                    accession_number=specimen.accession_number,
                    specimen_id=specimen.id,
                    specimen_type=specimen.specimen_type_name_en,
                    test_code=item.test_code,
                    test_name=item.test_name_en,
                    department_id=department.id,
                    department_code=department.code,
                    department_name=department.name_en,
                    current_order_status=order.status,
                    current_specimen_status=specimen.status,
                    current_result_status=result.status if result else ResultStatus.PENDING,
                    created_at=(
                        result.last_modified_at
                        if result and result.last_modified_at
                        else specimen.received_at
                    )
                    or specimen.collected_at,
                    tat_minutes=lab_test.tat_minutes,
                    source_actor=result.last_modified_by if result else specimen.received_by,
                )
            )
        return records

    def diagnostics(self) -> WorklistDiagnostics:
        active_orders = self.session.scalar(
            select(func.count(LabOrder.id)).where(LabOrder.status != OrderStatus.CANCELLED)
        ) or 0
        specimen_exists = exists(
            select(Specimen.id).join(SpecimenItem).where(
                Specimen.order_id == LabOrder.id,
                SpecimenItem.order_item_id == LabOrderItem.id,
                Specimen.is_current.is_(True),
                Specimen.status != SpecimenStatus.REJECTED,
            )
        )
        pending_collection = self.session.scalar(
            select(func.count(func.distinct(LabOrder.id)))
            .join(LabOrderItem, LabOrderItem.order_id == LabOrder.id)
            .join(LabTest, LabTest.id == LabOrderItem.lab_test_id)
            .where(LabOrder.status != OrderStatus.CANCELLED, ~specimen_exists)
        ) or 0
        collected = self.session.scalar(
            select(func.count(Specimen.id))
            .join(LabOrder, LabOrder.id == Specimen.order_id)
            .where(
                Specimen.status == SpecimenStatus.COLLECTED,
                LabOrder.status != OrderStatus.CANCELLED,
            )
        ) or 0
        received = self.session.scalar(
            select(func.count(Specimen.id))
            .join(LabOrder, LabOrder.id == Specimen.order_id)
            .where(
                Specimen.status == SpecimenStatus.RECEIVED,
                LabOrder.status != OrderStatus.CANCELLED,
            )
        ) or 0
        pending_results = self.session.scalar(
            select(func.count(LabOrderItem.id))
            .join(LabOrder, LabOrder.id == LabOrderItem.order_id)
            .join(SpecimenItem, SpecimenItem.order_item_id == LabOrderItem.id)
            .join(Specimen, Specimen.id == SpecimenItem.specimen_id)
            .outerjoin(Result, Result.order_item_id == LabOrderItem.id)
            .where(
                LabOrderItem.is_outlab.is_(False),
                LabOrder.status != OrderStatus.CANCELLED,
                Specimen.status == SpecimenStatus.RECEIVED,
                Specimen.is_current.is_(True),
                or_(Result.id.is_(None), Result.status == ResultStatus.PENDING),
            )
        ) or 0
        return WorklistDiagnostics(
            active_orders=active_orders,
            orders_pending_collection=pending_collection,
            collected_specimens=collected,
            received_specimens=received,
            pending_results=pending_results,
        )

    def list_departments(self) -> list[LaboratoryDepartment]:
        return list(
            self.session.scalars(
                select(LaboratoryDepartment)
                .order_by(
                    LaboratoryDepartment.is_active.desc(), LaboratoryDepartment.code
                )
            )
        )
