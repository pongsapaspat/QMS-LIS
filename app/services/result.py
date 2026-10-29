from datetime import date
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.exceptions import (
    InvalidResultOperationError,
    OrderNotFoundError,
    ResultNotFoundError,
)
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.order import LabOrder, LabOrderItem, OrderStatus
from app.models.result import Result, ResultRevision, ResultStatus
from app.models.specimen import Specimen, SpecimenStatus
from app.models.test_catalog import ReferenceRange
from app.repositories.audit import AuditRepository
from app.repositories.result import ResultRepository
from app.schemas.result import MultiResultSave, ResultEdit, ResultItemSave


class ResultService:
    def __init__(
        self,
        session: Session,
        repository: ResultRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or ResultRepository(session)
        self.audit_repository = audit_repository or AuditRepository(session)

    def worklist(
        self, **filters: object
    ) -> tuple[list[tuple[LabOrderItem, Specimen, Result | None]], int]:
        return self.repository.list_worklist(**filters)  # type: ignore[arg-type]

    def context(self, order_id: int) -> list[LabOrderItem]:
        if self.repository.get_order(order_id) is None:
            raise OrderNotFoundError("lab order not found")
        return self.repository.order_context(order_id)

    def save_multiple(
        self, order_id: int, data: MultiResultSave, *, actor_reference: str
    ) -> list[Result]:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        if order.status == OrderStatus.CANCELLED:
            raise InvalidResultOperationError("cancelled orders cannot accept results")
        items = {item.id: item for item in self.repository.order_context(order_id)}
        prepared: list[tuple[LabOrderItem, Specimen, ResultItemSave, dict[str, object]]] = []
        for submitted in data.items:
            item = items.get(submitted.order_item_id)
            if item is None:
                raise InvalidResultOperationError("order item not found in this order")
            specimen = self.repository.specimen_for_item(submitted.order_item_id)
            if specimen is None or specimen.status != SpecimenStatus.RECEIVED:
                raise InvalidResultOperationError(
                    "results may only be entered for received specimens"
                )
            existing = item.result
            if (
                existing is not None
                and submitted.version is not None
                and existing.version != submitted.version
            ):
                raise InvalidResultOperationError("concurrent result update conflict")
            prepared.append((item, specimen, submitted, self._interpret(item, submitted)))
        results: list[Result] = []
        try:
            for item, specimen, submitted, interpretation in prepared:
                existing = item.result
                if existing is None:
                    existing = Result(
                        order_item_id=item.id, specimen_id=specimen.id, result_type=item.result_type
                    )
                    self.session.add(existing)
                    self.session.flush()
                    event = "RESULT_ENTERED"
                    prior = None
                else:
                    prior = self._value_snapshot(existing)
                    if existing.status == ResultStatus.COMPLETED:
                        event = "RESULT_CORRECTED"
                    else:
                        event = "RESULT_UPDATED"
                    if event == "RESULT_CORRECTED" and not getattr(
                        submitted, "modification_reason", ""
                    ):
                        raise InvalidResultOperationError("a modification reason is required")
                reason = getattr(submitted, "modification_reason", "")
                if event == "RESULT_UPDATED" and not reason:
                    reason = "continued result entry"
                self._apply(existing, submitted, interpretation, actor_reference)
                if (
                    existing.status == ResultStatus.COMPLETED
                    and existing.abnormal_flag in {"LL", "HH"}
                    and not submitted.acknowledge_critical
                ):
                    raise InvalidResultOperationError(
                        "critical value acknowledgement is required before completion"
                    )
                if submitted.acknowledge_critical and existing.abnormal_flag in {"LL", "HH"}:
                    existing.critical_acknowledged_at = utc_now()
                    existing.critical_acknowledged_by = actor_reference
                    self._audit(
                        "CRITICAL_VALUE_ACKNOWLEDGED",
                        existing,
                        {"critical_acknowledged_at"},
                        "",
                        actor_reference,
                    )
                if prior is not None:
                    self.session.add(
                        ResultRevision(
                            result_id=existing.id,
                            previous_value=prior,
                            new_value=self._value_snapshot(existing),
                            previous_flag=prior.get("abnormal_flag"),
                            new_flag=existing.abnormal_flag,
                            modification_reason=reason,
                            modified_by=actor_reference,
                        )
                    )
                self._audit(
                    event,
                    existing,
                    {"value", "abnormal_flag", "status"},
                    reason,
                    actor_reference,
                )
                if existing.status == ResultStatus.COMPLETED:
                    self._audit("RESULT_COMPLETED", existing, {"status"}, "", actor_reference)
                results.append(existing)
            self._update_order_status(order, actor_reference)
            self.session.commit()
            return results
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError("result save could not be completed") from exc
        except Exception:
            self.session.rollback()
            raise

    def edit(self, result_id: int, data: ResultEdit, *, actor_reference: str) -> Result:
        result = self.session.get(Result, result_id)
        if result is None:
            raise ResultNotFoundError("result not found")
        return self.save_multiple(
            result.order_item.order_id,
            MultiResultSave(items=[data]),
            actor_reference=actor_reference,
        )[0]

    def _interpret(self, item: LabOrderItem, submitted: ResultItemSave) -> dict[str, object]:
        result_type = item.result_type
        if result_type == "NUMERIC":
            if submitted.numeric_value is None:
                raise InvalidResultOperationError("numeric result requires a numeric value")
            reference = self._match_range(item)
            flag = self._flag(submitted.numeric_value, reference) if reference else None
            return {"flag": flag, "range": self._range_snapshot(reference) if reference else None}
        if result_type == "TEXT":
            if submitted.text_value is None:
                raise InvalidResultOperationError("text result requires text")
            return {"flag": None, "range": None}
        if result_type in {"CATEGORICAL", "QUALITATIVE"}:
            if submitted.categorical_value is None:
                raise InvalidResultOperationError("categorical result requires an option")
            allowed = {option.code for option in self.repository.active_options(item.lab_test_id)}
            if submitted.categorical_value not in allowed:
                raise InvalidResultOperationError(
                    "categorical value is not configured for this test"
                )
            return {"flag": None, "range": None}
        raise InvalidResultOperationError("unsupported result type")

    def _match_range(self, item: LabOrderItem) -> ReferenceRange | None:
        patient = item.order.patient
        if patient.date_of_birth is None:
            age_days = None
        else:
            age_days = (date.today() - patient.date_of_birth).days
        for candidate in self.repository.active_ranges(item.lab_test_id):
            if candidate.sex not in {"ALL", (patient.sex or "").upper()}:
                continue
            if age_days is None:
                continue
            divisor = {"DAYS": 1, "MONTHS": 30, "YEARS": 365}[candidate.age_unit]
            age = age_days // divisor
            if candidate.minimum_age <= age <= candidate.maximum_age:
                return candidate
        return None

    @staticmethod
    def _flag(value: Decimal, reference: ReferenceRange) -> str:
        if reference.lower_critical is not None and value <= reference.lower_critical:
            return "LL"
        if value < reference.lower_value:
            return "L"
        if reference.upper_critical is not None and value >= reference.upper_critical:
            return "HH"
        if value > reference.upper_value:
            return "H"
        return "N"

    @staticmethod
    def _range_snapshot(reference: ReferenceRange) -> dict[str, object]:
        return {
            "id": reference.id,
            "lower_value": str(reference.lower_value),
            "upper_value": str(reference.upper_value),
            "lower_critical": str(reference.lower_critical)
            if reference.lower_critical is not None
            else None,
            "upper_critical": str(reference.upper_critical)
            if reference.upper_critical is not None
            else None,
            "display_text": reference.display_text,
        }

    def _apply(
        self,
        result: Result,
        submitted: ResultItemSave,
        interpretation: dict[str, object],
        actor: str,
    ) -> None:
        result.numeric_value, result.text_value, result.categorical_value = (
            submitted.numeric_value,
            submitted.text_value,
            submitted.categorical_value,
        )
        result.result_unit_snapshot = result.order_item.result_unit
        result.reference_range_snapshot = interpretation["range"]  # type: ignore[assignment]
        result.abnormal_flag = interpretation["flag"]  # type: ignore[assignment]
        result.status = ResultStatus.COMPLETED if submitted.complete else ResultStatus.IN_PROGRESS
        result.entered_at = result.entered_at or utc_now()
        result.entered_by = result.entered_by or actor
        result.last_modified_at, result.last_modified_by = utc_now(), actor
        result.version += 1
        if result.abnormal_flag not in {"LL", "HH"}:
            result.critical_acknowledged_at, result.critical_acknowledged_by = None, None

    @staticmethod
    def _value_snapshot(result: Result) -> dict[str, object]:
        return {
            "numeric_value": str(result.numeric_value)
            if result.numeric_value is not None
            else None,
            "text_value": result.text_value,
            "categorical_value": result.categorical_value,
            "abnormal_flag": result.abnormal_flag,
        }

    def _audit(self, event: str, result: Result, fields: set[str], reason: str, actor: str) -> None:
        self.audit_repository.add(
            AuditLog(
                event_type=event,
                entity_type="result",
                entity_id=result.id,
                changed_fields=sorted(fields),
                reason=reason,
                actor_reference=actor,
            )
        )

    def _update_order_status(self, order: LabOrder, actor: str) -> None:
        items = self.repository.order_context(order.id)
        completed = bool(items) and all(
            item.result is not None and item.result.status == ResultStatus.COMPLETED
            for item in items
        )
        target = OrderStatus.RESULTS_COMPLETED if completed else OrderStatus.RESULTS_IN_PROGRESS
        if order.status != target:
            order.status = target
            self.audit_repository.add(
                AuditLog(
                    event_type="ORDER_RESULTS_COMPLETED"
                    if completed
                    else "ORDER_RESULTS_IN_PROGRESS",
                    entity_type="lab_order",
                    entity_id=order.id,
                    changed_fields=["status"],
                    reason="",
                    actor_reference=actor,
                )
            )
