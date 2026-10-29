from fastapi import APIRouter, status

from app.api.dependencies import OrderServiceDependency, ResultServiceDependency
from app.core.security import ActorDependency, ResultReaderDependency, ResultReleaserDependency
from app.models.order import LabOrder
from app.schemas.order import LabOrderCreate, LabOrderResponse
from app.schemas.result import OrderRelease

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/{order_id}/release-preview")
def release_preview(
    order_id: int,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
) -> dict[str, object]:
    return service.release_preview(order_id)


@router.patch("/{order_id}/release", response_model=LabOrderResponse)
def release_order(
    order_id: int,
    data: OrderRelease,
    service: ResultServiceDependency,
    actor: ResultReleaserDependency,
) -> LabOrder:
    return service.release(order_id, data, actor_reference=actor.reference)


@router.post("", response_model=LabOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    data: LabOrderCreate,
    service: OrderServiceDependency,
    actor: ActorDependency,
) -> LabOrderResponse:
    return LabOrderResponse.model_validate(service.create(data, actor_reference=actor.reference))


@router.get("/{order_id}", response_model=LabOrderResponse)
def get_order(
    order_id: int,
    service: OrderServiceDependency,
    actor: ActorDependency,
) -> LabOrderResponse:
    return LabOrderResponse.model_validate(service.get(order_id))
