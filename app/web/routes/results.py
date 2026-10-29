from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import ResultServiceDependency, WorklistServiceDependency
from app.core.security import (
    ResultMutationDependency,
    ResultReaderDependency,
    ResultReleaserDependency,
    ResultVerifierDependency,
)
from app.domain.exceptions import InvalidResultOperationError
from app.models.order import LabOrderItem, OrderPriority
from app.models.result import ResultStatus
from app.schemas.result import (
    MultiResultSave,
    OrderRelease,
    ResultEdit,
    ResultItemSave,
    VerificationApproval,
    VerificationRejection,
)
from app.schemas.worklist import WorklistTaskStatus, WorklistTaskType
from app.web.templates import templates

router = APIRouter()


@router.get("/results/verification", response_class=HTMLResponse, name="verification_queue")
def verification_queue(
    request: Request,
    service: ResultServiceDependency,
    worklist_service: WorklistServiceDependency,
    actor: ResultReaderDependency,
    department_id: int | None = Query(default=None, ge=1),
    priority: OrderPriority | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    queue = service.verification_queue(
        department_id=department_id,
        priority=priority.value if priority else None,
        search=search,
        page=page,
        page_size=50,
    )
    return templates.TemplateResponse(
        request=request,
        name="results/verification_queue.html",
        context={
            "page_title": "Verification Queue",
            "queue": queue,
            "departments": worklist_service.departments(),
            "priorities": OrderPriority,
            "filters": {
                "department_id": department_id,
                "priority": priority.value if priority else "",
                "search": search or "",
            },
        },
    )


@router.get(
    "/results/verification/orders/{order_id}",
    response_class=HTMLResponse,
    name="verification_order",
)
def verification_order(
    order_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="results/verification_detail.html",
        context={
            "page_title": "Result Verification",
            "context": service.verification_context(order_id),
            "errors": [],
            "form_values": {},
        },
    )


@router.post(
    "/results/verification/{result_id}/verify",
    name="verification_approve",
    response_model=None,
)
async def verification_approve(
    result_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultVerifierDependency,
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    order_id = int(str(form.get("order_id", "0")))
    values = {
        "comment": str(form.get("comment", "")),
        "bypass_four_eyes": form.get("bypass_four_eyes") == "on",
    }
    try:
        service.verify(
            result_id,
            VerificationApproval.model_validate(values),
            actor_reference=actor.reference,
            actor_role=actor.role,
        )
    except (InvalidResultOperationError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="results/verification_detail.html",
            status_code=422,
            context={
                "page_title": "Result Verification",
                "context": service.verification_context(order_id),
                "errors": [str(exc)],
                "form_values": {str(result_id): values},
            },
        )
    return RedirectResponse(request.url_for("verification_queue"), status_code=303)


@router.post(
    "/results/verification/{result_id}/reject",
    name="verification_reject",
    response_model=None,
)
async def verification_reject(
    result_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultVerifierDependency,
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    order_id = int(str(form.get("order_id", "0")))
    reason = str(form.get("reason", ""))
    try:
        data = VerificationRejection.model_validate({"reason": reason})
        service.reject_verification(result_id, data, actor_reference=actor.reference)
    except (InvalidResultOperationError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="results/verification_detail.html",
            status_code=422,
            context={
                "page_title": "Result Verification",
                "context": service.verification_context(order_id),
                "errors": [str(exc)],
                "form_values": {str(result_id): {"reason": reason}},
            },
        )
    return RedirectResponse(request.url_for("verification_queue"), status_code=303)


@router.get("/results/release", response_class=HTMLResponse, name="release_queue")
def release_queue(
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
    priority: OrderPriority | None = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="results/release_queue.html",
        context={
            "page_title": "Release Queue",
            "queue": service.release_queue(
                priority=priority.value if priority else None,
                search=search,
                page=page,
                page_size=50,
            ),
            "priorities": OrderPriority,
            "filters": {
                "priority": priority.value if priority else "",
                "search": search or "",
            },
        },
    )


@router.get(
    "/results/release/orders/{order_id}",
    response_class=HTMLResponse,
    name="release_order_preview",
)
def release_order_preview(
    order_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="results/release_detail.html",
        context={
            "page_title": "Release Order",
            "context": service.release_preview(order_id),
            "errors": [],
            "form_values": {},
        },
    )


@router.post(
    "/results/release/orders/{order_id}",
    name="release_order_action",
    response_model=None,
)
async def release_order_action(
    order_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReleaserDependency,
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    comment = str(form.get("comment", ""))
    try:
        service.release(
            order_id,
            OrderRelease.model_validate({"comment": comment}),
            actor_reference=actor.reference,
        )
    except (InvalidResultOperationError, ValueError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="results/release_detail.html",
            status_code=422,
            context={
                "page_title": "Release Order",
                "context": service.release_preview(order_id),
                "errors": [str(exc)],
                "form_values": {"comment": comment},
            },
        )
    return RedirectResponse(request.url_for("release_queue"), status_code=303)


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
    items: list[ResultItemSave] = []
    for item in service.context(order_id):
        key = str(item.id)
        value = str(form.get(f"value_{key}", "")).strip()
        if not value:
            continue
        payload: dict[str, object] = {
            "order_item_id": item.id,
            "version": item.result.version if item.result else None,
            "complete": form.get(f"complete_{key}") == "on",
            "acknowledge_critical": form.get(f"ack_{key}") == "on",
        }
        if item.result_type == "NUMERIC":
            payload["numeric_value"] = value
        elif item.result_type == "TEXT":
            payload["text_value"] = value
        else:
            payload["categorical_value"] = value
        if item.result and item.result.status in {
            ResultStatus.COMPLETED,
            ResultStatus.VERIFICATION_REJECTED,
            ResultStatus.VERIFIED,
        }:
            payload["modification_reason"] = str(
                form.get(f"reason_{key}", "")
            )
            items.append(ResultEdit.model_validate(payload))
        else:
            items.append(ResultItemSave.model_validate(payload))
    if items:
        service.save_multiple(
            order_id, MultiResultSave(items=items), actor_reference=actor.reference
        )
    return RedirectResponse(request.url_for("result_entry", order_id=order_id), status_code=303)
