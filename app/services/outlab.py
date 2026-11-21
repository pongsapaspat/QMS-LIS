from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.domain.exceptions import InvalidResultOperationError
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.order import LabOrder, LabOrderItem, OrderStatus
from app.models.outlab import OutlabCase, OutlabDocument
from app.models.patient import Patient
from app.models.specimen import Specimen, SpecimenItem, SpecimenStatus

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class OutlabService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, case_id: int) -> OutlabCase:
        case = self.session.scalar(
            select(OutlabCase)
            .where(OutlabCase.id == case_id)
            .options(
                selectinload(OutlabCase.documents),
                selectinload(OutlabCase.order_item)
                .selectinload(LabOrderItem.order)
                .selectinload(LabOrder.patient),
            )
        )
        if case is None:
            raise InvalidResultOperationError("Outlab item not found")
        return case

    def specimen(self, case: OutlabCase) -> Specimen | None:
        return self.session.scalar(
            select(Specimen)
            .join(SpecimenItem)
            .where(SpecimenItem.order_item_id == case.order_item_id, Specimen.is_current.is_(True))
        )

    def queue(self, status: str, search: str, page: int) -> list[OutlabCase]:
        statement = (
            select(OutlabCase)
            .join(OutlabCase.order_item)
            .join(LabOrderItem.order)
            .join(LabOrder.patient)
            .where(LabOrder.status.notin_([OrderStatus.CANCELLED, OrderStatus.RELEASED]))
        )
        if status:
            if status not in {"PENDING_SEND", "SENT", "RECEIVED", "CHECKED"}:
                raise InvalidResultOperationError("Unknown Outlab status")
            statement = statement.where(OutlabCase.status == status)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    LabOrder.order_number.ilike(term),
                    Patient.hn.ilike(term),
                    LabOrderItem.test_code.ilike(term),
                    LabOrderItem.test_name_en.ilike(term),
                    OutlabCase.lab_name.ilike(term),
                )
            )
        return list(
            self.session.scalars(
                statement.options(
                    selectinload(OutlabCase.order_item)
                    .selectinload(LabOrderItem.order)
                    .selectinload(LabOrder.patient)
                )
                .order_by(LabOrder.priority.desc(), OutlabCase.id)
                .offset((page - 1) * 25)
                .limit(26)
            )
        )

    def _editable(self, case: OutlabCase) -> None:
        if case.order_item.order.status in {OrderStatus.CANCELLED, OrderStatus.RELEASED}:
            raise InvalidResultOperationError("Cancelled or released orders cannot change Outlab")
        specimen = self.specimen(case)
        if specimen is None or specimen.status != SpecimenStatus.RECEIVED:
            raise InvalidResultOperationError(
                "Collect and receive the separate Outlab specimen first"
            )

    @staticmethod
    def text(value: str, limit: int, required: bool = False) -> str:
        value = " ".join(value.split())
        if len(value) > limit or (required and not value):
            raise InvalidResultOperationError(f"Enter a value of at most {limit} characters")
        return value

    def _transition(
        self,
        case: OutlabCase,
        expected: str,
        values: dict,
        event: str,
        actor: str,
        reason: str = "",
    ) -> None:
        changed = self.session.execute(
            update(OutlabCase)
            .where(
                OutlabCase.id == case.id,
                OutlabCase.status == expected,
            )
            .values(**values),
            execution_options={"synchronize_session": False},
        )
        if changed.rowcount != 1:
            raise InvalidResultOperationError("Outlab status changed; reload before trying again")
        self.session.expire(case)
        self.session.add(
            AuditLog(
                event_type=event,
                entity_type="outlab_case",
                entity_id=case.id,
                changed_fields=sorted(values),
                actor_reference=actor,
                reason=reason,
            )
        )

    def send(self, case_id: int, lab_name: str, external_reference: str, notes: str, actor: str):
        case = self.get(case_id)
        self._editable(case)
        if case.status != "PENDING_SEND":
            raise InvalidResultOperationError("Only pending Outlab items may be sent")
        values = dict(
            status="SENT",
            lab_name=self.text(lab_name, 200, True),
            external_reference=self.text(external_reference, 150) or None,
            notes=self.text(notes, 2000) or None,
            sent_at=utc_now(),
            sent_by=actor,
        )
        try:
            self._transition(
                case, "PENDING_SEND", values, "OUTLAB_SENT", actor, values["notes"] or ""
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def receive(
        self, case_id: int, filename: str, content: bytes, external_reference: str, actor: str
    ):
        case = self.get(case_id)
        self._editable(case)
        if case.status != "SENT":
            raise InvalidResultOperationError("Only sent Outlab items may receive a report")
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise InvalidResultOperationError("Attach a PDF, PNG or JPEG up to 10 MB")
        signatures = [
            (b"%PDF-", "application/pdf"),
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff", "image/jpeg"),
        ]
        content_type = next(
            (mime for signature, mime in signatures if content.startswith(signature)), None
        )
        if content_type is None:
            raise InvalidResultOperationError(
                "Only PDF, PNG or JPEG source documents are supported"
            )
        filename = (
            "".join(c for c in filename.replace("\\", "/").rsplit("/", 1)[-1] if c.isprintable())[
                :255
            ]
            or "outlab-report"
        )
        values = dict(
            status="RECEIVED",
            received_at=utc_now(),
            received_by=actor,
            external_reference=self.text(external_reference, 150) or case.external_reference,
        )
        try:
            self._transition(case, "SENT", values, "OUTLAB_DOCUMENT_RECEIVED", actor)
            self.session.add(
                OutlabDocument(
                    case_id=case.id,
                    filename=filename,
                    content_type=content_type,
                    content=content,
                    uploaded_at=utc_now(),
                    uploaded_by=actor,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def check(self, case_id: int, actor: str, confirmed: bool):
        case = self.get(case_id)
        self._editable(case)
        if case.status != "RECEIVED" or not case.documents or not confirmed:
            raise InvalidResultOperationError(
                "Confirm the patient, requested test and original document"
            )
        try:
            self._transition(
                case,
                "RECEIVED",
                dict(status="CHECKED", checked_at=utc_now(), checked_by=actor),
                "OUTLAB_DOCUMENT_CHECKED",
                actor,
            )
            self.session.flush()
            from app.services.result import ResultService

            ResultService(self.session)._update_order_verification(case.order_item.order, actor)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def reject_document(self, case_id: int, reason: str, actor: str):
        case = self.get(case_id)
        self._editable(case)
        if case.status != "RECEIVED":
            raise InvalidResultOperationError(
                "Only unchecked documents may be returned for replacement"
            )
        reason = self.text(reason, 1000, True)
        try:
            self._transition(
                case, "RECEIVED", dict(status="SENT"), "OUTLAB_DOCUMENT_REJECTED", actor, reason
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
