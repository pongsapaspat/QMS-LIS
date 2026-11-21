from datetime import date
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.result_formatting import (
    display_panel_results,
    format_reference_text,
    format_result_number,
)
from app.core.time import app_date_range_utc
from app.domain.exceptions import (
    InvalidResultOperationError,
    OrderNotFoundError,
    ResultNotFoundError,
)
from app.domain.panels import interpret_panel
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.order import LabOrder, LabOrderItem, OrderStatus
from app.models.result import Result, ResultRevision, ResultStatus
from app.models.specimen import Specimen, SpecimenStatus
from app.models.test_catalog import ReferenceRange
from app.repositories.audit import AuditRepository
from app.repositories.result import ResultRepository
from app.schemas.result import (
    AmendmentOpen,
    MultiResultSave,
    OrderRelease,
    ResultEdit,
    ResultItemSave,
    VerificationApproval,
    VerificationRejection,
)
from app.services.report_identity import capture_identity
from app.services.report_layout import prepare_report


class ResultService:
    def __init__(
        self,
        session: Session,
        repository: ResultRepository | None = None,
        audit_repository: AuditRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or ResultRepository(session)
        self.audit_repository = audit_repository or AuditRepository(session)
        self.settings = settings or get_settings()

    def worklist(
        self, **filters: object
    ) -> tuple[list[tuple[LabOrderItem, Specimen, Result | None]], int]:
        return self.repository.list_worklist(**filters)  # type: ignore[arg-type]

    def context(self, order_id: int) -> list[LabOrderItem]:
        if self.repository.get_order(order_id) is None:
            raise OrderNotFoundError("lab order not found")
        return self.repository.order_context(order_id)

    def entry_metadata(self, items: list[LabOrderItem]) -> dict[int, dict[str, object]]:
        metadata = {}
        for item in items:
            if item.is_outlab or item.result_type != "NUMERIC":
                continue
            reference = self._match_range(item)
            snapshot = self._range_snapshot(reference) if reference else {}
            if item.result and item.result.status == ResultStatus.RELEASED:
                snapshot = item.result.reference_range_snapshot or {}
            value = item.result.numeric_value if item.result else None
            lower, upper = snapshot.get("lower_critical"), snapshot.get("upper_critical")
            critical = value is not None and (
                (lower is not None and value <= Decimal(str(lower)))
                or (upper is not None and value >= Decimal(str(upper)))
            )
            metadata[item.id] = {
                "reference_text": format_reference_text(snapshot.get("display_text")) or (
                    f"{format_result_number(snapshot['lower_value'], None)} – "
                    f"{format_result_number(snapshot['upper_value'], None)}"
                    if snapshot.get("lower_value") is not None else "ยังไม่ได้กำหนดค่าอ้างอิง"
                ),
                "lower_critical": lower, "upper_critical": upper, "critical": bool(critical),
            }
        return metadata

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
            if item.is_outlab:
                raise InvalidResultOperationError("Outlab accepts original documents only, not result values")
            specimen = self.repository.specimen_for_item(submitted.order_item_id)
            if specimen is None or not specimen.is_current or specimen.status != SpecimenStatus.RECEIVED:
                raise InvalidResultOperationError(
                    "results may only be entered for received specimens"
                )
            existing = item.result
            if existing is not None and existing.status == ResultStatus.RELEASED:
                raise InvalidResultOperationError(
                    "released results cannot be edited; use an amendment workflow"
                )
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
                locked = self.session.execute(update(Specimen).where(
                    Specimen.id == specimen.id, Specimen.is_current.is_(True),
                    Specimen.status == SpecimenStatus.RECEIVED,
                ).values(status=SpecimenStatus.RECEIVED, updated_at=Specimen.updated_at)
                    .execution_options(synchronize_session=False))
                if locked.rowcount != 1:
                    raise InvalidResultOperationError("สิ่งส่งตรวจถูก Reject หรือเปลี่ยนสถานะแล้ว กรุณาโหลดใหม่")
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
                    if existing.status in {
                        ResultStatus.COMPLETED,
                        ResultStatus.VERIFICATION_REJECTED,
                        ResultStatus.VERIFIED,
                        ResultStatus.AMENDMENT_REQUESTED,
                    }:
                        event = (
                            "RESULT_AMENDED"
                            if existing.status == ResultStatus.AMENDMENT_REQUESTED
                            else "RESULT_CORRECTED"
                        )
                    else:
                        event = "RESULT_UPDATED"
                    if event in {"RESULT_CORRECTED", "RESULT_AMENDED"} and not getattr(
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
        result = self.repository.get_result(result_id)
        if result is None:
            raise ResultNotFoundError("result not found")
        return self.save_multiple(
            result.order_item.order_id,
            MultiResultSave(items=[data]),
            actor_reference=actor_reference,
        )[0]

    def open_amendment(
        self, result_id: int, data: AmendmentOpen, *, actor_reference: str
    ) -> Result:
        result = self.repository.get_result(result_id)
        if result is None:
            raise ResultNotFoundError("result not found")
        order = result.order_item.order
        if result.status != ResultStatus.RELEASED:
            raise InvalidResultOperationError("only released results may be amended")
        if order.status not in {OrderStatus.RELEASED, OrderStatus.RESULTS_IN_PROGRESS}:
            raise InvalidResultOperationError("order is not eligible for amendment")
        try:
            result.status = ResultStatus.AMENDMENT_REQUESTED
            result.amendment_opened_at = utc_now()
            result.amendment_opened_by = actor_reference
            result.amendment_reason = data.reason
            result.version += 1
            order.status = OrderStatus.RESULTS_IN_PROGRESS
            order.verified_at = None
            order.verified_by = None
            order.released_at = None
            order.released_by = None
            order.released_by_snapshot = None
            self._audit(
                "RESULT_AMENDMENT_OPENED",
                result,
                {"status", "amendment_opened_at", "amendment_opened_by"},
                data.reason,
                actor_reference,
            )
            self.audit_repository.add(
                AuditLog(
                    event_type="ORDER_AMENDMENT_OPENED",
                    entity_type="lab_order",
                    entity_id=order.id,
                    changed_fields=["status", "verified_at", "released_at"],
                    reason=data.reason,
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
            self.session.refresh(result)
            return result
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError("amendment could not be opened") from exc

    def verification_queue(
        self,
        *,
        department_id: int | None,
        priority: str | None,
        search: str | None,
        page: int,
        page_size: int,
        group_orders: bool = False,
    ) -> dict[str, object]:
        results, total = self.repository.list_verification_queue(
            department_id=department_id,
            priority=priority,
            search=search,
            offset=(page - 1) * page_size,
            limit=page_size,
            group_orders=group_orders,
        )
        items = [self._verification_item(result) for result in results]
        if group_orders:
            orders: dict[int, list[dict[str, object]]] = {}
            for result, item in zip(results, items, strict=True):
                orders.setdefault(result.order_item.order_id, []).append(item)
            items = [
                {**tests[0], "results": tests, "pending_count": len(tests)}
                for tests in orders.values()
            ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def verification_context(self, order_id: int) -> dict[str, object]:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        return {
            "order": self._order_summary(order),
            "results": self._order_result_details(order),
            "outlab_cases": [item.outlab for item in order.items if item.outlab],
            "admin_bypass_enabled": (
                self.settings.enforce_four_eyes_check
                and self.settings.allow_admin_four_eyes_bypass
            ),
        }

    def verify(
        self,
        result_id: int,
        data: VerificationApproval,
        *,
        actor_reference: str,
        actor_role: str,
    ) -> Result:
        result = self.repository.get_result(result_id)
        if result is None:
            raise ResultNotFoundError("result not found")
        self._check_version(result, data.version)
        self._validate_verification(result)
        same_actor = actor_reference in {result.entered_by, result.last_modified_by}
        bypass = False
        if self.settings.enforce_four_eyes_check and same_actor:
            bypass = (
                actor_role == "ADMIN"
                and data.bypass_four_eyes
                and self.settings.allow_admin_four_eyes_bypass
            )
            if not bypass:
                raise InvalidResultOperationError(
                    "self-verification is prohibited by the four-eyes policy"
                )
        try:
            result.status = ResultStatus.VERIFIED
            result.verified_at = utc_now()
            result.verified_by = actor_reference
            result.verified_by_snapshot = capture_identity(
                self.session, actor_reference, self.settings, require_complete=True
            )
            result.verification_comment = data.comment
            result.verification_rejected_at = None
            result.verification_rejected_by = None
            result.verification_rejection_reason = None
            result.version += 1
            self._audit(
                "RESULT_VERIFIED",
                result,
                {"status", "verified_at", "verified_by", "verification_comment"},
                data.comment or "",
                actor_reference,
            )
            if bypass:
                self._audit(
                    "ADMIN_FOUR_EYES_BYPASS",
                    result,
                    {"status", "verified_by"},
                    "explicit administrative four-eyes bypass",
                    actor_reference,
                )
            self._update_order_verification(result.order_item.order, actor_reference)
            self.session.commit()
            self.session.refresh(result)
            return result
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError("result verification could not be completed") from exc
        except Exception:
            self.session.rollback()
            raise

    def reject_verification(
        self,
        result_id: int,
        data: VerificationRejection,
        *,
        actor_reference: str,
    ) -> Result:
        result = self.repository.get_result(result_id)
        if result is None:
            raise ResultNotFoundError("result not found")
        self._check_version(result, data.version)
        if result.status != ResultStatus.COMPLETED:
            raise InvalidResultOperationError(
                "only completed results may be rejected from verification"
            )
        if result.order_item.order.status == OrderStatus.CANCELLED:
            raise InvalidResultOperationError("cancelled orders cannot be reviewed")
        try:
            result.status = ResultStatus.VERIFICATION_REJECTED
            result.verification_rejected_at = utc_now()
            result.verification_rejected_by = actor_reference
            result.verification_rejection_reason = data.reason
            result.verification_comment = None
            result.verified_by_snapshot = None
            result.version += 1
            order = result.order_item.order
            order.status = OrderStatus.RESULTS_IN_PROGRESS
            order.verified_at = None
            order.verified_by = None
            self._audit(
                "RESULT_VERIFICATION_REJECTED",
                result,
                {
                    "status",
                    "verification_rejected_at",
                    "verification_rejected_by",
                    "verification_rejection_reason",
                },
                data.reason,
                actor_reference,
            )
            self.session.commit()
            self.session.refresh(result)
            return result
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError(
                "verification rejection could not be completed"
            ) from exc
        except Exception:
            self.session.rollback()
            raise

    def release_queue(
        self,
        *,
        priority: str | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        orders, total = self.repository.list_release_queue(
            priority=priority,
            search=search,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "items": [self._release_order(order) for order in orders],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def release_preview(self, order_id: int) -> dict[str, object]:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        issues = self._release_issues(order)
        return {
            "order": self._order_summary(order),
            "results": self._order_result_details(order),
            "outlab_cases": [item.outlab for item in order.items if item.outlab],
            "release_ready": not issues,
            "issues": issues,
        }

    def report_context(self, order_id: int, *, actor_reference: str) -> dict[str, object]:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        if order.status != OrderStatus.RELEASED:
            raise InvalidResultOperationError(
                "รายงานผลฉบับสมบูรณ์เปิดได้หลังจาก Release ผลแล้วเท่านั้น"
            )
        if not order.items or any(
            (not item.outlab or not item.outlab.ready) if item.is_outlab else
            (item.result is None or item.result.status != ResultStatus.RELEASED)
            for item in order.items
        ):
            raise InvalidResultOperationError("ผลตรวจใน Order นี้ยัง Release ไม่ครบถ้วน")

        accessions = list(
            dict.fromkeys(
                item.result.specimen.accession_number
                for item in order.items
                if item.result is not None
            )
        )
        results = []
        for item in order.items:
            result = item.result
            if item.is_outlab or result is None:
                continue
            reference = result.reference_range_snapshot or {}
            results.append(
                {
                    "result_id": result.id,
                    "result_type": item.result_type,
                    "department_code": item.lab_test.department.code,
                    "department_name": item.lab_test.department.name_th,
                    "category_name": item.lab_test.category.name_th,
                    "category_name_en": item.lab_test.category.name_en,
                    "specimen": result.specimen,
                    "entered_by": result.last_modified_by or result.entered_by,
                    "entered_at": result.last_modified_at or result.entered_at,
                    "reporter_snapshot": result.last_modified_by_snapshot or result.entered_by_snapshot,
                    "approver_snapshot": result.released_by_snapshot,
                    "parameters": display_panel_results(result.parameter_results),
                    "test_code": item.test_code,
                    "test_name": item.test_name_th or item.test_name_en,
                    "test_name_en": item.test_name_en,
                    "result_value": self._result_value(result),
                    "unit": result.result_unit_snapshot,
                    "reference_text": format_reference_text(reference.get("display_text"))
                    or self._reference_interval(reference),
                    "abnormal_flag": result.abnormal_flag,
                    "verified_at": result.verified_at,
                    "verified_by": result.verified_by,
                    "released_at": result.released_at,
                    "released_by": result.released_by,
                }
            )

        try:
            self.audit_repository.add(
                AuditLog(
                    event_type="LAB_REPORT_VIEWED",
                    entity_type="lab_order",
                    entity_id=order.id,
                    changed_fields=[],
                    reason="เปิดดูรายงานผลตรวจ",
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError("ไม่สามารถบันทึกการเปิดดูรายงานได้") from exc

        reporter = max(
            (item.result for item in order.items if item.result and item.result.entered_by),
            key=lambda result: result.entered_at.timestamp() if result.entered_at else float("-inf"),
            default=None,
        )
        return prepare_report({
            "order": order,
            "reported_by": reporter.entered_by if reporter else None,
            "reported_at": reporter.entered_at if reporter else None,
            "patient": order.patient,
            "accession_numbers": accessions,
            "results": results,
            "outlab_cases": [item.outlab for item in order.items if item.outlab],
        }, self.settings)

    def report_list(
        self,
        *,
        search: str | None,
        date_from: date | None,
        date_to: date | None,
        page: int,
        page_size: int,
    ) -> dict[str, object]:
        if date_from is not None and date_to is not None and date_from > date_to:
            raise InvalidResultOperationError("วันที่เริ่มต้นต้องไม่อยู่หลังวันที่สิ้นสุด")
        released_from, released_before = app_date_range_utc(
            date_from, date_to, self.settings.timezone
        )
        orders, total = self.repository.list_released_orders(
            search=search,
            released_from=released_from,
            released_before=released_before,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return {
            "items": [self._release_order(order) for order in orders],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def audit_report_pdf_download(self, order_id: int, *, actor_reference: str) -> None:
        self.audit_repository.add(
            AuditLog(
                event_type="LAB_REPORT_PDF_DOWNLOADED",
                entity_type="lab_order",
                entity_id=order_id,
                changed_fields=[],
                reason="ดาวน์โหลดรายงานผลตรวจ PDF",
                actor_reference=actor_reference,
            )
        )
        self.session.commit()

    def release(
        self,
        order_id: int,
        data: OrderRelease,
        *,
        actor_reference: str,
    ) -> LabOrder:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        issues = self._release_issues(order)
        if issues:
            raise InvalidResultOperationError("; ".join(issues))
        released_at = utc_now()
        identity = capture_identity(self.session, actor_reference, self.settings, require_complete=True)
        try:
            for item in order.items:
                if item.is_outlab:
                    continue
                result = item.result
                if result is None:
                    raise InvalidResultOperationError(
                        f"required result {item.test_code} is missing"
                    )
                if result.status == ResultStatus.RELEASED:
                    continue
                result.status = ResultStatus.RELEASED
                result.released_at = released_at
                result.released_by = actor_reference
                result.released_by_snapshot = identity.copy()
                result.version += 1
                self._audit(
                    "RESULT_AMENDMENT_RELEASED"
                    if result.amendment_opened_at is not None
                    else "RESULT_RELEASED",
                    result,
                    {"status", "released_at", "released_by"},
                    data.comment or "",
                    actor_reference,
                )
            order.status = OrderStatus.RELEASED
            order.released_at = released_at
            order.released_by = actor_reference
            order.released_by_snapshot = identity.copy()
            self.audit_repository.add(
                AuditLog(
                    event_type="ORDER_RELEASED",
                    entity_type="lab_order",
                    entity_id=order.id,
                    changed_fields=["released_at", "released_by", "status"],
                    reason=data.comment or "",
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
            self.session.refresh(order)
            return order
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidResultOperationError("order release could not be completed") from exc
        except Exception:
            self.session.rollback()
            raise

    def _interpret(self, item: LabOrderItem, submitted: ResultItemSave) -> dict[str, object]:
        result_type = item.result_type
        if result_type in {'CBC', 'UA', 'INFLUENZA_AB'}:
            rows = interpret_panel(item.parameter_definitions or [],
                                   submitted.parameter_values or {}, submitted.complete)
            return {'flag': 'A' if any(row['flag'] in {'H', 'L', 'A'} for row in rows) else None,
                    'range': None, 'parameters': rows}
        if submitted.parameter_values is not None:
            raise InvalidResultOperationError('This test does not accept panel parameters')
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
            allowed = {option.code: option for option in self.repository.active_options(item.lab_test_id)}
            if submitted.categorical_value not in allowed:
                raise InvalidResultOperationError(
                    "categorical value is not configured for this test"
                )
            option = allowed[submitted.categorical_value]
            return {"flag": None, "range": None, "categorical_label": {
                "code": option.code, "label_th": option.label_th, "label_en": option.label_en,
            }}
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
        # A correction that keeps the same code also keeps the original wording.
        label = interpretation.get("categorical_label")
        if not (result.categorical_label_snapshot
                and result.categorical_label_snapshot.get("code") == submitted.categorical_value):
            result.categorical_label_snapshot = label  # type: ignore[assignment]
        result.parameter_values = submitted.parameter_values
        result.parameter_results = interpretation.get('parameters')
        result.reference_range_snapshot = interpretation["range"]  # type: ignore[assignment]
        result.abnormal_flag = interpretation["flag"]  # type: ignore[assignment]
        result.status = ResultStatus.COMPLETED if submitted.complete else ResultStatus.IN_PROGRESS
        identity = capture_identity(
            self.session, actor, self.settings, require_complete=submitted.complete
        )
        if not result.entered_by:
            result.entered_by_snapshot = identity.copy()
        result.last_modified_by_snapshot = identity.copy()
        result.entered_at = result.entered_at or utc_now()
        result.entered_by = result.entered_by or actor
        result.last_modified_at, result.last_modified_by = utc_now(), actor
        result.verified_at = None
        result.verified_by = None
        result.verified_by_snapshot = None
        result.verification_comment = None
        result.verification_rejected_at = None
        result.verification_rejected_by = None
        result.verification_rejection_reason = None
        result.released_at = None
        result.released_by = None
        result.released_by_snapshot = None
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
            "categorical_label_snapshot": result.categorical_label_snapshot,
            "parameter_values": result.parameter_values,
            "parameter_results": result.parameter_results,
            "entered_by_snapshot": result.entered_by_snapshot,
            "last_modified_by_snapshot": result.last_modified_by_snapshot,
            "verified_by_snapshot": result.verified_by_snapshot,
            "released_by_snapshot": result.released_by_snapshot,
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
        completed_statuses = {
            ResultStatus.COMPLETED,
            ResultStatus.VERIFIED,
            ResultStatus.RELEASED,
        }
        completed = bool(items) and all(
            (item.outlab is not None and item.outlab.ready) if item.is_outlab else
            (item.result is not None and item.result.status in completed_statuses) for item in items
        )
        target = OrderStatus.RESULTS_COMPLETED if completed else OrderStatus.RESULTS_IN_PROGRESS
        if order.status != target:
            order.status = target
            order.verified_at = None
            order.verified_by = None
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

    @staticmethod
    def _check_version(result: Result, version: int | None) -> None:
        if version is not None and result.version != version:
            raise InvalidResultOperationError("concurrent result update conflict")

    @staticmethod
    def _validate_verification(result: Result) -> None:
        if result.order_item.is_outlab:
            raise InvalidResultOperationError("Outlab documents are checked, not result-verified")
        if result.status != ResultStatus.COMPLETED:
            raise InvalidResultOperationError("only completed results may be verified")
        if result.specimen.status != SpecimenStatus.RECEIVED:
            raise InvalidResultOperationError("the associated specimen has not been received")
        if not result.specimen.is_current:
            raise InvalidResultOperationError("the associated specimen has been replaced")
        if result.order_item.order.status == OrderStatus.CANCELLED:
            raise InvalidResultOperationError("cancelled orders cannot be verified")
        if result.abnormal_flag in {"LL", "HH"} and result.critical_acknowledged_at is None:
            raise InvalidResultOperationError(
                "critical value acknowledgement is required before verification"
            )
        has_value = any(
            value is not None
            for value in (result.numeric_value, result.text_value, result.categorical_value)
        )
        if not has_value:
            if result.parameter_results:
                interpret_panel(result.order_item.parameter_definitions or [],
                                result.parameter_values or {}, True)
                return
            raise InvalidResultOperationError("result validation has not passed")

    def _update_order_verification(self, order: LabOrder, actor: str) -> None:
        items = self.repository.order_context(order.id)
        external_ready = all(item.outlab and item.outlab.ready for item in items if item.is_outlab)
        internal_items = [item for item in items if not item.is_outlab]
        fully_verified = (
            bool(items)
            and all(
                item.result is not None
                and item.result.status in {ResultStatus.VERIFIED, ResultStatus.RELEASED}
                for item in internal_items
            )
            and (not internal_items or any(item.result and item.result.status == ResultStatus.VERIFIED
                                          for item in internal_items))
        )
        specimens_received = all(
            item.result is not None and item.result.specimen.status == SpecimenStatus.RECEIVED
            for item in internal_items
        )
        critical_resolved = all(
            item.result is not None
            and (
                item.result.abnormal_flag not in {"LL", "HH"}
                or item.result.critical_acknowledged_at is not None
            )
            for item in internal_items
        )
        if not (external_ready and fully_verified and specimens_received and critical_resolved):
            return
        order.status = OrderStatus.RESULTS_VERIFIED
        order.verified_at = utc_now()
        order.verified_by = actor
        self.audit_repository.add(
            AuditLog(
                event_type="ORDER_VERIFIED",
                entity_type="lab_order",
                entity_id=order.id,
                changed_fields=["status", "verified_at", "verified_by"],
                reason="internal results verified and Outlab documents checked"
                if any(item.is_outlab for item in items) else "all required results verified",
                actor_reference=actor,
            )
        )

    def _release_issues(self, order: LabOrder) -> list[str]:
        if order.status == OrderStatus.CANCELLED:
            return ["cancelled orders cannot be released"]
        if order.status == OrderStatus.RELEASED:
            return ["order has already been released"]
        issues: list[str] = []
        for item in order.items:
            if item.is_outlab:
                if not item.outlab or not item.outlab.ready:
                    issues.append(f"รอใบผล Outlab / ตรวจเช็กเอกสาร: {item.test_code}")
                continue
            result = item.result
            if result is None:
                issues.append(f"required result {item.test_code} is missing")
                continue
            if result.status == ResultStatus.VERIFICATION_REJECTED:
                issues.append(f"result {item.test_code} requires correction")
            elif result.status not in {ResultStatus.VERIFIED, ResultStatus.RELEASED}:
                issues.append(f"result {item.test_code} is not verified")
            if result.specimen.status == SpecimenStatus.REJECTED:
                issues.append(f"specimen for {item.test_code} is rejected")
            elif result.specimen.status != SpecimenStatus.RECEIVED:
                issues.append(f"specimen for {item.test_code} is not received")
            elif not result.specimen.is_current:
                issues.append(f"specimen for {item.test_code} has been replaced")
            if (
                result.abnormal_flag in {"LL", "HH"}
                and result.critical_acknowledged_at is None
            ):
                issues.append(f"critical value for {item.test_code} is not acknowledged")
        if order.status != OrderStatus.RESULTS_VERIFIED and not issues:
            issues.append("order is not fully verified")
        return issues

    @staticmethod
    def _result_value(result: Result) -> str | None:
        if result.parameter_results:
            return f"{len(result.parameter_results)} parameters"
        if result.numeric_value is not None:
            return format_result_number(result.numeric_value)
        if result.text_value:
            return result.text_value
        if result.categorical_value:
            snapshot = result.categorical_label_snapshot or {}
            if snapshot.get("label_en") or snapshot.get("label_th"):
                return snapshot.get("label_en") or snapshot.get("label_th")
            # Legacy rows without a snapshot can still resolve inactive options.
            for option in result.order_item.lab_test.qualitative_options:
                if option.code == result.categorical_value:
                    return option.label_en or option.label_th or option.code
        return result.categorical_value

    @staticmethod
    def _reference_interval(reference: dict[str, object]) -> str | None:
        lower = reference.get("lower_value")
        upper = reference.get("upper_value")
        return (f"{format_result_number(lower, None)} – {format_result_number(upper, None)}"
                if lower is not None and upper is not None else None)

    def _verification_item(self, result: Result) -> dict[str, object]:
        item = result.order_item
        order = item.order
        return {
            "result_id": result.id,
            "parameters": display_panel_results(result.parameter_results),
            "order_id": order.id,
            "order_number": order.order_number,
            "patient_hn": order.patient.hn,
            "patient_name": order.patient.display_name,
            "accession_number": result.specimen.accession_number,
            "specimen_type": result.specimen.specimen_type_name_en,
            "department_id": item.lab_test.department_id,
            "department_code": item.lab_test.department.code,
            "test_code": item.test_code,
            "test_name": item.test_name_en,
            "result_value": self._result_value(result),
            "unit": result.result_unit_snapshot,
            "reference_range": {**result.reference_range_snapshot, "display_text":
                format_reference_text(result.reference_range_snapshot.get("display_text"))
                or self._reference_interval(result.reference_range_snapshot)}
                if result.reference_range_snapshot else None,
            "abnormal_flag": result.abnormal_flag,
            "critical": result.abnormal_flag in {"LL", "HH"},
            "entered_by": result.entered_by,
            "entered_at": result.entered_at,
            "status": result.status,
            "priority": order.priority,
            "version": result.version,
        }

    def _verification_detail(
        self, result: Result, history: list[AuditLog] | None = None
    ) -> dict[str, object]:
        detail = self._verification_item(result)
        detail.update(
            {
                "verified_by": result.verified_by,
                "verified_at": result.verified_at,
                "verification_comment": result.verification_comment,
                "verification_rejected_by": result.verification_rejected_by,
                "verification_rejected_at": result.verification_rejected_at,
                "verification_rejection_reason": result.verification_rejection_reason,
                "critical_acknowledged_by": result.critical_acknowledged_by,
                "critical_acknowledged_at": result.critical_acknowledged_at,
                "revisions": [
                    {
                        "id": revision.id,
                        "previous_value": revision.previous_value,
                        "new_value": revision.new_value,
                        "previous_flag": revision.previous_flag,
                        "new_flag": revision.new_flag,
                        "modification_reason": revision.modification_reason,
                        "modified_at": revision.modified_at,
                        "modified_by": revision.modified_by,
                    }
                    for revision in result.revisions
                ],
                "history": [
                    {
                        "event_type": event.event_type,
                        "actor_reference": event.actor_reference,
                        "occurred_at": event.occurred_at,
                        "reason": event.reason,
                    }
                    for event in (
                        history
                        if history is not None
                        else self.audit_repository.list_for_entity("result", result.id)
                    )
                    if event.event_type
                    in {
                        "CRITICAL_VALUE_ACKNOWLEDGED",
                        "RESULT_VERIFIED",
                        "RESULT_VERIFICATION_REJECTED",
                        "RESULT_RELEASED",
                        "ADMIN_FOUR_EYES_BYPASS",
                    }
                ],
            }
        )
        return detail

    def _order_result_details(self, order: LabOrder) -> list[dict[str, object]]:
        results = [item.result for item in order.items if not item.is_outlab and item.result is not None]
        events = self.audit_repository.list_for_entities(
            "result", [result.id for result in results]
        )
        history_by_result: dict[int, list[AuditLog]] = {}
        for event in events:
            history_by_result.setdefault(event.entity_id, []).append(event)
        return [
            self._verification_detail(result, history_by_result.get(result.id, []))
            for result in results
        ]

    @staticmethod
    def _order_summary(order: LabOrder) -> dict[str, object]:
        accessions = sorted(
            {
                item.result.specimen.accession_number
                for item in order.items
                if item.result is not None
            }
        )
        return {
            "id": order.id,
            "order_number": order.order_number,
            "patient_hn": order.patient.hn,
            "patient_name": order.patient.display_name,
            "priority": order.priority,
            "status": order.status,
            "accession_numbers": accessions,
            "verified_at": order.verified_at,
            "verified_by": order.verified_by,
            "released_at": order.released_at,
            "released_by": order.released_by,
        }

    def _release_order(self, order: LabOrder) -> dict[str, object]:
        results = [item.result for item in order.items if item.result is not None]
        return {
            **self._order_summary(order),
            "result_count": len(results),
            "outlab_count": sum(item.is_outlab for item in order.items),
            "has_critical": any(
                result.abnormal_flag in {"LL", "HH"} for result in results
            ),
        }
