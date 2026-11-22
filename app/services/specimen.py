from typing import Any, cast
from uuid import uuid4

from sqlalchemy import exists, true, update
from sqlalchemy.engine import CursorResult
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
from app.models.result import Result
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
        all_specimens = self.repository.list_order_specimens(order.id)
        specimens_by_item = {
            link.order_item_id: specimen
            for specimen in all_specimens
            if specimen.is_current
            for link in specimen.items
        }
        grouped: dict[tuple[int, str], SpecimenRequirement] = {}
        for order_item in self.repository.list_order_items(order.id):
            lab_test = order_item.lab_test
            specimen_type = lab_test.specimen_type
            current = specimens_by_item.get(order_item.id)
            # Keep the original specimen requirement when catalog settings change later.
            type_id = current.specimen_type_id if current else specimen_type.id
            group = f"OUTLAB-{order_item.id}" if order_item.is_outlab else "INTERNAL"
            requirement = grouped.setdefault(
                (type_id, group),
                SpecimenRequirement(
                    specimen_type_id=type_id,
                    collection_group=group,
                    outlab_lab_name=order_item.outlab.lab_name if order_item.outlab else None,
                    specimen_type_code=current.specimen_type_code
                    if current
                    else specimen_type.code,
                    specimen_type_name_th=current.specimen_type_name_th
                    if current
                    else specimen_type.name_th,
                    specimen_type_name_en=current.specimen_type_name_en
                    if current
                    else specimen_type.name_en,
                    items=[],
                    specimen=current,
                    history=[
                        s
                        for s in all_specimens
                        if not s.is_current
                        and s.specimen_type_id == type_id
                        and s.collection_group == group
                    ],
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
        previous = self.repository.get_order_specimen(
            order.id, data.specimen_type_id, data.collection_group
        )
        if previous is not None and (
            previous.status != SpecimenStatus.REJECTED or data.replaces_specimen_id != previous.id
        ):
            raise InvalidSpecimenOperationError(
                "a specimen for this group exists; "
                "recollection must identify the current rejected specimen"
            )
        if previous is None and data.replaces_specimen_id is not None:
            raise InvalidSpecimenOperationError(
                "replacement does not match this order and specimen group"
            )

        matching_items = [
            item
            for item in self.repository.list_order_items(order.id)
            if item.lab_test.specimen_type_id == data.specimen_type_id
            and (f"OUTLAB-{item.id}" if item.is_outlab else "INTERNAL") == data.collection_group
        ]
        if previous:
            matching_items = [link.order_item for link in previous.items]
        if not matching_items:
            raise InvalidSpecimenOperationError(
                "specimen type is not required by this laboratory order"
            )
        specimen_type = self.repository.get_specimen_type(data.specimen_type_id)
        if specimen_type is None or not specimen_type.is_active:
            raise InvalidSpecimenOperationError("active specimen type not found")
        collected_at = data.collected_at or utc_now()
        if previous and (
            collected_at < (previous.rejected_at or previous.collected_at)
            or collected_at > utc_now()
        ):
            raise InvalidSpecimenOperationError(
                "recollection time must be after rejection and not in the future"
            )
        specimen = Specimen(
            accession_number=f"P-{uuid4().hex[:22]}",
            order_id=order.id,
            specimen_type_id=specimen_type.id,
            collection_group=data.collection_group,
            specimen_type_code=previous.specimen_type_code if previous else specimen_type.code,
            specimen_type_name_th=previous.specimen_type_name_th
            if previous
            else specimen_type.name_th,
            specimen_type_name_en=previous.specimen_type_name_en
            if previous
            else specimen_type.name_en,
            replaces_specimen_id=previous.id if previous else None,
            collected_at=collected_at,
            collected_by=actor_reference,
            collection_note=data.collection_note,
        )
        try:
            if previous:
                changed = cast(CursorResult[Any], self.session.execute(
                    update(Specimen)
                    .where(
                        Specimen.id == previous.id,
                        Specimen.is_current.is_(True),
                        Specimen.status == SpecimenStatus.REJECTED,
                    )
                    .values(is_current=False),
                    execution_options={"synchronize_session": False},
                ))
                if changed.rowcount != 1:
                    self.session.rollback()
                    raise InvalidSpecimenOperationError(
                        "specimen changed; reload before recollecting"
                    )
                self.session.expire(previous)
            self.repository.add(specimen)
            specimen.accession_number = f"SPC{collected_at:%Y%m%d}-{specimen.id:06d}"
            specimen.items = [SpecimenItem(order_item_id=item.id) for item in matching_items]
            self.audit_repository.add(
                AuditLog(
                    event_type="SPECIMEN_RECOLLECTED" if previous else "SPECIMEN_COLLECTED",
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
                        + (["replaces_specimen_id"] if previous else [])
                    ),
                    reason=f"Replacement for {previous.accession_number}" if previous else "",
                    actor_reference=actor_reference,
                )
            )
            if previous:
                self.audit_repository.add(
                    AuditLog(
                        event_type="SPECIMEN_REPLACED",
                        entity_type="specimen",
                        entity_id=previous.id,
                        changed_fields=["is_current"],
                        reason=f"Replaced by {specimen.accession_number}",
                        actor_reference=actor_reference,
                    )
                )
            self.session.commit()
            self.session.refresh(specimen)
        except IntegrityError as exc:
            self.session.rollback()
            if (
                self.repository.get_order_specimen(
                    order.id, data.specimen_type_id, data.collection_group
                )
                is not None
            ):
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
        self._get_collectable_order(specimen.order_id)
        if not specimen.can_reject:
            raise InvalidSpecimenOperationError("Reject ได้เฉพาะสิ่งส่งตรวจที่ยังไม่ลงผลและยังไม่ส่ง Outlab")
        original_status = specimen.status
        try:
            self._transition_collected(
                specimen,
                dict(
                    status=SpecimenStatus.REJECTED,
                    rejection_reason_code=data.rejection_reason_code,
                    rejection_reason=data.rejection_reason,
                    rejected_at=utc_now(),
                    rejected_by=actor_reference,
                ),
                source_status=original_status,
                rejecting=True,
            )
            self.audit_repository.add(
                AuditLog(
                    event_type="SPECIMEN_REJECTED",
                    entity_type="specimen",
                    entity_id=specimen.id,
                    changed_fields=[
                        "rejected_at",
                        "rejected_by",
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
        if specimen.status != SpecimenStatus.COLLECTED or not specimen.is_current:
            raise InvalidSpecimenOperationError("only collected specimens may be received")
        received_at = data.received_at or utc_now()
        if received_at < specimen.collected_at:
            raise InvalidSpecimenOperationError("received at cannot be earlier than collected at")
        if received_at > utc_now():
            raise InvalidSpecimenOperationError("received at cannot be in the future")
        try:
            self._transition_collected(
                specimen,
                dict(
                    status=SpecimenStatus.RECEIVED,
                    received_at=received_at,
                    received_by=actor_reference,
                    receiving_note=data.receiving_note,
                ),
            )
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
            if (
                self.repository.all_required_specimens_received(order.id)
                and order.status == OrderStatus.ORDERED
            ):
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

    def _transition_collected(
        self,
        specimen: Specimen,
        values: dict[str, Any],
        source_status: str = SpecimenStatus.COLLECTED,
        rejecting: bool = False,
    ) -> None:
        guard = ~exists().where(Result.specimen_id == specimen.id) if rejecting else true()
        changed = cast(CursorResult[Any], self.session.execute(
            update(Specimen)
            .where(
                Specimen.id == specimen.id,
                Specimen.status == source_status,
                Specimen.is_current.is_(True),
                guard,
            )
            .values(**values),
            execution_options={"synchronize_session": False},
        ))
        if changed.rowcount != 1:
            self.session.rollback()
            raise InvalidSpecimenOperationError(
                "specimen status changed; reload before trying again"
            )
        self.session.expire(specimen)

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
        if order.status in {OrderStatus.CANCELLED, OrderStatus.RELEASED}:
            raise InvalidSpecimenOperationError(
                "cancelled or released orders cannot receive specimens"
            )
        return order

    def _get_receivable_order(self, order_id: int) -> LabOrder:
        order = self.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found")
        if order.status == OrderStatus.CANCELLED:
            raise InvalidSpecimenOperationError("cancelled orders cannot receive specimens")
        return order
