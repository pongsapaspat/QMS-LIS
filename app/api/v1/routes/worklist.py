from fastapi import APIRouter, Query

from app.api.dependencies import WorklistServiceDependency
from app.core.security import ResultReaderDependency
from app.domain.collection import CollectionRoom
from app.models.order import OrderPriority
from app.schemas.worklist import WorklistResponse, WorklistTaskStatus, WorklistTaskType

router = APIRouter(prefix="/worklist", tags=["worklist"])


@router.get("", response_model=WorklistResponse)
def unified_worklist(
    service: WorklistServiceDependency,
    actor: ResultReaderDependency,
    task_type: WorklistTaskType | None = None,
    department_id: int | None = Query(default=None, ge=1),
    priority: OrderPriority | None = None,
    status: WorklistTaskStatus | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    collection_room: CollectionRoom | None = None,
) -> WorklistResponse:
    return service.list_tasks(
        task_type=task_type,
        department_id=department_id,
        priority=priority,
        status=status,
        search=search,
        page=page,
        page_size=page_size,
        collection_room=collection_room,
    )
