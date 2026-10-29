from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import ResultServiceDependency, WorklistServiceDependency
from app.core.security import ResultMutationDependency, ResultReaderDependency
from app.models.order import LabOrderItem, OrderPriority
from app.schemas.result import MultiResultSave, ResultItemSave
from app.schemas.worklist import WorklistTaskStatus, WorklistTaskType

templates = Jinja2Templates(directory="app/templates")

router = APIRouter()


@router.get("/worklist", response_class=HTMLResponse, name="worklist")
def worklist(
    request: Request,
    service: WorklistServiceDependency,
    actor: ResultReaderDependency,
    task_type: WorklistTaskType | None = None,
    department_id: int | None = Query(default=None, ge=1),
    priority: OrderPriority | None = None,
    status: WorklistTaskStatus | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    response = service.list_tasks(
        task_type=task_type,
        department_id=department_id,
        priority=priority,
        status=status,
        search=search,
        page=page,
        page_size=50,
    )
    return templates.TemplateResponse(
        request=request,
        name="results/worklist.html",
        context={
            "page_title": "Laboratory Worklist",
            "worklist": response,
            "task_types": WorklistTaskType,
            "task_statuses": WorklistTaskStatus,
            "priorities": OrderPriority,
            "departments": service.departments(),
            "filters": {
                "task_type": task_type.value if task_type else "",
                "department_id": department_id,
                "priority": priority.value if priority else "",
                "status": status.value if status else "",
                "search": search or "",
            },
        },
    )


@router.get("/worklist/orders/{order_id}", response_class=HTMLResponse, name="result_entry")
def entry(
    order_id: int, request: Request, service: ResultServiceDependency, actor: ResultReaderDependency
) -> HTMLResponse:
    items: list[LabOrderItem] = service.context(order_id)
    return templates.TemplateResponse(
        request=request,
        name="results/entry.html",
        context={
            "page_title": "Result Entry",
            "order_id": order_id,
            "items": items,
            "errors": [],
        },
    )


@router.post("/worklist/orders/{order_id}", name="result_save")
async def save(
    order_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultMutationDependency,
) -> RedirectResponse:
    form = await request.form()
    items = []
    for item in service.context(order_id):
        key = str(item.id)
        value = str(form.get(f"value_{key}", "")).strip()
        if not value:
            continue
        payload: dict[str, object] = {
            "order_item_id": item.id,
            "complete": form.get(f"complete_{key}") == "on",
            "acknowledge_critical": form.get(f"ack_{key}") == "on",
        }
        if item.result_type == "NUMERIC":
            payload["numeric_value"] = value
        elif item.result_type == "TEXT":
            payload["text_value"] = value
        else:
            payload["categorical_value"] = value
        items.append(ResultItemSave.model_validate(payload))
    if items:
        service.save_multiple(
            order_id, MultiResultSave(items=items), actor_reference=actor.reference
        )
    return RedirectResponse(request.url_for("result_entry", order_id=order_id), status_code=303)
