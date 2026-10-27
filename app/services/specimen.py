from uuid import uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.exceptions import (
    InvalidSpecimenOperationError,
    OrderNotFoundError,
    SpecimenNotFoundError,
)
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.order import LabOrder, OrderStatus
from app.models.specimen import Specimen, SpecimenItem, SpecimenStatus
from app.repositories.audit import AuditRepository
from app.repositories.specimen import SpecimenRepository
from app.schemas.specimen import (
    SpecimenCollectRequest,
    SpecimenReceiptRequest,
    SpecimenRejectRequest,
    SpecimenRequirement,
    SpecimenRequirementItem,
)


class SpecimenService:
    def __init__(
        self,
        session: Session,
        repository: SpecimenRepository | None = None,
        audit_repository: AuditRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or SpecimenRepository(session)
        self.audit_repository = audit_repository or AuditRepository(session)

    def requirements(self, order_id: int) -> list[SpecimenRequirement]:
        order = self._get_collectable_order(order_id)
        specimens = {
            specimen.specimen_type_id: specimen
            for specimen in self.repository.list_order_specimens(order.id)
        }
        grouped: dict[int, SpecimenRequirement] = {}
        for order_item in self.repository.list_order_items(order.id):
            lab_test = order_item.lab_test
            specimen_type = lab_test.specimen_type
            requirement = grouped.setdefault(
                specimen_type.id,
                SpecimenRequirement(
                    specimen_type_id=specimen_type.id,
                    specimen_type_code=specimen_type.code,
                    specimen_type_name_th=specimen_type.name_th,
                    specimen_type_name_en=specimen_type.name_en,
                    items=[],
                    specimen=specimens.get(specimen_type.id),
                ),
            )
            requirement.items.append(
                SpecimenRequirementItem(
                    id=order_item.id,
                    lab_test_id=lab_test.id,
                    test_code=order_item.test_code,
                    test_name_th=order_item.test_name_th,
                    test_name_en=order_item.test_name_en,
                )
            )
        return list(sorted(grouped.values(), key=lambda item: item.specimen_type_code))

    def collect(self, data: SpecimenCollectRequest, *, actor_reference: str) -> Specimen:
        order = self._get_collectable_order(data.order_id)
        if self.repository.get_order_specimen(order.id, data.specimen_type_id) is not None:
            raise InvalidSpecimenOperationError(
                "a specimen for this order and specimen type already exists"
            )

        matching_items = [
            item
            for item in self.repository.list_order_items(order.id)
            if item.lab_test.specimen_type_id == data.specimen_type_id
        ]
        if not matching_items:
            raise InvalidSpecimenOperationError(
                "specimen type is not required by this laboratory order"
            )
        specimen_type = self.repository.get_specimen_type(data.specimen_type_id)
        if specimen_type is None or not specimen_type.is_active:
            raise InvalidSpecimenOperationError("active specimen type not found")
        collected_at = data.collected_at or utc_now()
        specimen = Specimen(
            accession_number=f"P-{uuid4().hex[:22]}",
            order_id=order.id,
            specimen_type_id=specimen_type.id,
            specimen_type_code=specimen_type.code,
            specimen_type_name_th=specimen_type.name_th,
            specimen_type_name_en=specimen_type.name_en,
            collected_at=collected_at,
            collected_by=actor_reference,
            collection_note=data.collection_note,
        )
        try:
            self.repository.add(specimen)
            specimen.accession_number = f"SPC{collected_at:%Y%m%d}-{specimen.id:06d}"
            specimen.items = [SpecimenItem(order_item_id=item.id) for item in matching_items]
            self.audit_repository.add(
                AuditLog(
                    event_type="SPECIMEN_COLLECTED",
                    entity_type="specimen",
                    entity_id=specimen.id,
                    changed_fields=sorted(
                        [
                            "accession_number",
                            "collection_note",
                            "collected_at",
                            "collected_by",
                            "order_id",
                            "specimen_type_id",
                            "status",
                        ]
                    ),
                    reason="",
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
            self.session.refresh(specimen)
        except IntegrityError as exc:
            self.session.rollback()
            if self.repository.get_order_specimen(order.id, data.specimen_type_id) is not None:
                raise InvalidSpecimenOperationError(
                    "a specimen for this order and specimen type already exists"
                ) from exc
            raise InvalidSpecimenOperationError("specimen collection could not be saved") from exc
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidSpecimenOperationError("specimen collection could not be saved") from exc
        return self.get(specimen.id)

    def reject(
        self, specimen_id: int, data: SpecimenRejectRequest, *, actor_reference: str
    ) -> Specimen:
        specimen = self.get(specimen_id)
        if specimen.status != SpecimenStatus.COLLECTED:
            raise InvalidSpecimenOperationError("only collected specimens may be rejected")
        specimen.status = SpecimenStatus.REJECTED
        specimen.rejection_reason_code = data.rejection_reason_code
        specimen.rejection_reason = data.rejection_reason
        specimen.rejected_at = utc_now()
        try:
            self.audit_repository.add(
                AuditLog(
                    event_type="SPECIMEN_REJECTED",
                    entity_type="specimen",
                    entity_id=specimen.id,
                    changed_fields=[
                        "rejected_at",
                        "rejection_reason",
                        "rejection_reason_code",
                        "status",
                    ],
                    reason=data.rejection_reason or "",
                    actor_reference=actor_reference,
                )
            )
            self.session.commit()
            self.session.refresh(specimen)
        except IntegrityError as exc:
            self.session.rollback()
            raise InvalidSpecimenOperationError("specimen rejection could not be saved") from exc
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise InvalidSpecimenOperationError("specimen rejection could not be saved") from exc
        return self.get(specimen.id)

    def receive(
        self, specimen_id: int, data: SpecimenReceiptRequest, *, actor_reference: str
    ) -> Specimen:
        specimen = self.get(specimen_id)
        order = self._get_receivable_order(specimen.order_id)
        if specimen.status != SpecimenStatus.COLLECTED:
            raise InvalidSpecimenOperationError("only collected specimens may be received")
        received_at = data.received_at or utc_now()
        if received_at < specimen.collected_at:
            raise InvalidSpecimenOperationError("received at cannot be earlier than collected at")
        if received_at > utc_now():
            raise InvalidSpecimenOperationError("received at cannot be in the future")
        specimen.status = SpecimenStatus.RECEIVED
        specimen.received_at = received_at
        specimen.received_by = actor_reference
        specimen.receiving_note = data.receiving_note
        try:
            self.audit_repository.add(
                AuditLog(
                    event_type="SPECIMEN_RECEIVED",
                    entity_type="specimen",
                    entity_id=specimen.id,
                    changed_fields=["received_at", "received_by", "receiving_note", "status"],
                    reason=data.receiving_note or "",
                    actor_reference=actor_reference,
                )
            )
            if self.repository.all_required_specimens_received(order.id):
                order.status = OrderStatus.SPECIMENS_RECEIVED
                self.audit_repository.add(
                    AuditLog(
                        event_type="ORDER_SPECIMENS_RECEIVED",
                        entity_type="lab_order",
                        entity_id=order.id,
                        changed_fields=["status"],
                        reason="",
                        actor_reference=actor_reference,
                    )
                )
            self.session.commit()
            self.session.refresh(specimen)
        except (IntegrityError, SQLAlchemyError) as exc:
            self.session.rollback()
            raise InvalidSpecimenOperationError("specimen receipt could not be saved") from exc
        return self.get(specimen.id)

    def get(self, specimen_id: int) -> Specimen:
        specimen = self.repository.get_specimen(specimen_id)
        if specimen is None:
            raise SpecimenNotFoundError("specimen not found")
        return specimen

    def get_by_accession_number(self, accession_number: str) -> Specimen:
        specimen = self.repository.get_by_accession_number(accession_number)
        if specimen is None:
            raise SpecimenNotFoundError("specimen not found")
        return specimen

    def receiving_queue(
        self, *, status: str | None = SpecimenStatus.COLLECTED, accession_number: str | None = None
    ) -> list[Specimen]:
        return self.repository.list_receiving_queue(
            status=status, accession_number=accession_number, limit=100
        )

    def _get_collectable_order(self, order_id: int) -> LabOrder:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        if order.status == OrderStatus.CANCELLED:
            raise InvalidSpecimenOperationError("cancelled orders cannot receive specimens")
        return order

    def _get_receivable_order(self, order_id: int) -> LabOrder:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        if order.status == OrderStatus.CANCELLED:
            raise InvalidSpecimenOperationError("cancelled orders cannot receive specimens")
        return order
