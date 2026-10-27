from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import ResultServiceDependency
from app.core.security import ResultMutationDependency, ResultReaderDependency
from app.models.order import LabOrderItem
from app.schemas.result import MultiResultSave, ResultItemSave

templates = Jinja2Templates(directory="app/templates")

router = APIRouter()


@router.get("/worklist", response_class=HTMLResponse, name="worklist")
def worklist(
    request: Request, service: ResultServiceDependency, actor: ResultReaderDependency
) -> HTMLResponse:
    rows, total = service.worklist(
        department_id=None, status=None, search=None, offset=0, limit=100
    )
    return templates.TemplateResponse(
        request=request,
        name="results/worklist.html",
        context={"page_title": "Laboratory Worklist", "rows": rows, "total": total},
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
