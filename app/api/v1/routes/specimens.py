
from fastapi import APIRouter, status

from app.api.dependencies import SpecimenServiceDependency
from app.core.security import SpecimenCollectorDependency
from app.schemas.specimen import (
    SpecimenCollectRequest,
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
) -> list[SpecimenRequirement]:
    return service.requirements(order_id)


@router.post("", response_model=SpecimenResponse, status_code=status.HTTP_201_CREATED)
def collect_specimen(
    data: SpecimenCollectRequest,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(
        service.collect(data, actor_reference=actor.reference)
    )


@router.get("/{specimen_id}", response_model=SpecimenResponse)
def get_specimen(
    specimen_id: int,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> SpecimenResponse:
    return SpecimenResponse.model_validate(service.get(specimen_id))


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
