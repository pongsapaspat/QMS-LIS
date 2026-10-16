
from fastapi import APIRouter, status

from app.api.dependencies import OrderServiceDependency
from app.core.security import ActorDependency
from app.schemas.order import LabOrderCreate, LabOrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=LabOrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    data: LabOrderCreate,
    service: OrderServiceDependency,
    actor: ActorDependency,
) -> LabOrderResponse:
    return LabOrderResponse.model_validate(
        service.create(data, actor_reference=actor.reference)
    )


@router.get("/{order_id}", response_model=LabOrderResponse)
def get_order(
    order_id: int,
    service: OrderServiceDependency,
    actor: ActorDependency,
) -> LabOrderResponse:
    return LabOrderResponse.model_validate(service.get(order_id))
