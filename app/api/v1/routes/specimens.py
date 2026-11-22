from fastapi import APIRouter, Query, status

from app.api.dependencies import SpecimenServiceDependency
from app.core.security import SpecimenCollectorDependency, SpecimenReceivingReaderDependency
from app.domain.collection import CollectionRoom
from app.schemas.specimen import (
    SpecimenCollectRequest,
    SpecimenReceiptRequest,
    SpecimenRejectRequest,
    SpecimenRequirement,
    SpecimenResponse,
)

router = APIRouter(prefix="/specimens", tags=["specimens"])
order_router = APIRouter(prefix="/orders", tags=["specimens"])


@order_router.get("/{order_id}/specimen-requirements", response_model=list[SpecimenRequirement])
def get_specimen_requirements(
    order_id: int,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
    collection_room: CollectionRoom | None = None,
) -> list[SpecimenRequirement]:
    return service.requirements(order_id, collection_room=collection_room)


@router.post("", response_model=SpecimenResponse, status_code=status.HTTP_201_CREATED)
def collect_specimen(
    data: SpecimenCollectRequest,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
    collection_room: CollectionRoom | None = None,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(service.collect(
        data, actor_reference=actor.reference, collection_room=collection_room
    ))


@router.get("/{specimen_id:int}", response_model=SpecimenResponse)
def get_specimen(
    specimen_id: int,
    service: SpecimenServiceDependency,
    actor: SpecimenReceivingReaderDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(service.get(specimen_id))


@router.get("/accession/{accession_number}", response_model=SpecimenResponse)
def get_specimen_by_accession_number(
    accession_number: str,
    service: SpecimenServiceDependency,
    actor: SpecimenReceivingReaderDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(service.get_by_accession_number(accession_number))


@router.get("/receiving-queue", response_model=list[SpecimenResponse])
def receiving_queue(
    service: SpecimenServiceDependency,
    actor: SpecimenReceivingReaderDependency,
    specimen_status: str | None = Query(default="COLLECTED", alias="status"),
    accession_number: str | None = Query(default=None, max_length=24),
) -> list[SpecimenResponse]:
    allowed_statuses = {"COLLECTED", "RECEIVED", "REJECTED"}
    if specimen_status is not None and specimen_status not in allowed_statuses:
        specimen_status = None
    return [
        SpecimenResponse.model_validate(specimen)
        for specimen in service.receiving_queue(
            status=specimen_status,
            accession_number=accession_number.strip() if accession_number else None,
        )
    ]


@router.patch("/{specimen_id}/rejection", response_model=SpecimenResponse)
def reject_specimen(
    specimen_id: int,
    data: SpecimenRejectRequest,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(
        service.reject(specimen_id, data, actor_reference=actor.reference)
    )


@router.patch("/{specimen_id}/receipt", response_model=SpecimenResponse)
def receive_specimen(
    specimen_id: int,
    data: SpecimenReceiptRequest,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(
        service.receive(specimen_id, data, actor_reference=actor.reference)
    )
