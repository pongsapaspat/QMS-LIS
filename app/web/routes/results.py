from contextlib import suppress
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import AfterValidator, BeforeValidator

from app.api.dependencies import ResultServiceDependency, WorklistServiceDependency
from app.core.security import (
    ReportReaderDependency,
    ResultMutationDependency,
    ResultReaderDependency,
    ResultReleaserDependency,
    ResultVerifierDependency,
)
from app.domain.exceptions import InvalidResultOperationError
from app.models.order import LabOrder, LabOrderItem, OrderPriority
from app.models.result import ResultStatus
from app.schemas.result import (
    AmendmentOpen,
    MultiResultSave,
    OrderRelease,
    ResultEdit,
    ResultItemSave,
    VerificationApproval,
    VerificationRejection,
)
from app.schemas.worklist import WorklistTaskStatus, WorklistTaskType
from app.services.report_pdf import build_lab_report_pdf
from app.web.query import empty_string_to_none, positive_int_or_none
from app.web.templates import templates

router = APIRouter()


@router.get("/results/verification", response_class=HTMLResponse, name="verification_queue")
def verification_queue(
    request: Request,
    service: ResultServiceDependency,
    worklist_service: WorklistServiceDependency,
    actor: ResultReaderDependency,
    department_id: Annotated[
        int | None,
        BeforeValidator(empty_string_to_none),
        AfterValidator(positive_int_or_none),
    ] = None,
    priority: Annotated[OrderPriority | None, BeforeValidator(empty_string_to_none)] = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    queue = service.verification_queue(
        department_id=department_id,
        priority=priority.value if priority else None,
        search=search,
        page=page,
        page_size=50,
        group_orders=True,
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


@router.post(
    "/results/{result_id}/amendments",
    name="open_result_amendment",
)
async def open_result_amendment(
    result_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
) -> RedirectResponse:
    form = await request.form()
    result = service.open_amendment(
        result_id,
        AmendmentOpen(reason=str(form.get("reason", ""))),
        actor_reference=actor.reference,
    )
    return RedirectResponse(
        request.url_for("result_entry", order_id=result.order_item.order_id),
        status_code=303,
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
            "actor_role": actor.role,
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
                "actor_role": actor.role,
                "errors": [str(exc)],
                "form_values": {str(result_id): values},
            },
        )
    return RedirectResponse(
        f"{request.url_for('verification_queue')}?success=result-verified", status_code=303
    )


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
                "actor_role": actor.role,
                "errors": [str(exc)],
                "form_values": {str(result_id): {"reason": reason}},
            },
        )
    return RedirectResponse(
        f"{request.url_for('result_entry', order_id=order_id)}?success=result-rejected",
        status_code=303,
    )


@router.get("/results/release", response_class=HTMLResponse, name="release_queue")
def release_queue(
    request: Request,
    service: ResultServiceDependency,
    actor: ResultReaderDependency,
    priority: Annotated[OrderPriority | None, BeforeValidator(empty_string_to_none)] = None,
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


@router.get(
    "/results/reports",
    response_class=HTMLResponse,
    name="lab_reports",
)
def lab_reports(
    request: Request,
    service: ResultServiceDependency,
    actor: ReportReaderDependency,
    search: str | None = Query(default=None, max_length=100),
    date_from: Annotated[date | None, BeforeValidator(empty_string_to_none)] = None,
    date_to: Annotated[date | None, BeforeValidator(empty_string_to_none)] = None,
    page: int = Query(default=1, ge=1),
) -> HTMLResponse:
    page_size = 25
    errors: list[str] = []
    try:
        reports = service.report_list(
            search=search,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except InvalidResultOperationError as exc:
        errors.append(str(exc))
        reports = {"items": [], "total": 0, "page": page, "page_size": page_size}
    return templates.TemplateResponse(
        request=request,
        name="results/reports.html",
        context={
            "page_title": "รายงานผลตรวจ",
            "reports": reports,
            "search": search or "",
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
            "errors": errors,
            "has_previous": page > 1,
            "has_next": page * page_size < cast(int, reports["total"]),
        },
    )


@router.get(
    "/results/reports/orders/{order_id}",
    response_class=HTMLResponse,
    name="lab_report",
)
def lab_report(
    order_id: int,
    request: Request,
    service: ResultServiceDependency,
    actor: ReportReaderDependency,
) -> HTMLResponse:
    try:
        context = service.report_context(order_id, actor_reference=actor.reference)
    except InvalidResultOperationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="results/report_unavailable.html",
            status_code=409,
            context={
                "page_title": "รายงานผลตรวจยังไม่พร้อม",
                "order_id": order_id,
                "error": str(exc),
            },
        )
    return templates.TemplateResponse(
        request=request,
        name="results/report.html",
        context={"page_title": "รายงานผลตรวจ", "context": context},
    )


@router.get(
    "/results/reports/orders/{order_id}/pdf",
    response_class=Response,
    name="lab_report_pdf",
)
def lab_report_pdf(
    order_id: int,
    service: ResultServiceDependency,
    actor: ReportReaderDependency,
) -> Response:
    context = service.report_context(order_id, actor_reference=actor.reference)
    pdf = build_lab_report_pdf(context)
    service.audit_report_pdf_download(order_id, actor_reference=actor.reference)
    order = cast(LabOrder, context["order"])
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="QMS-LIS-{order.order_number}.pdf"')
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
    return RedirectResponse(
        f"{request.url_for('lab_report', order_id=order_id)}?success=results-released",
        status_code=303,
    )


@router.get("/worklist", response_class=HTMLResponse, name="worklist")
def worklist(
    request: Request,
    service: WorklistServiceDependency,
    actor: ResultReaderDependency,
    task_type: Annotated[WorklistTaskType | None, BeforeValidator(empty_string_to_none)] = None,
    department_id: Annotated[
        int | None,
        BeforeValidator(empty_string_to_none),
        AfterValidator(positive_int_or_none),
    ] = None,
    priority: Annotated[OrderPriority | None, BeforeValidator(empty_string_to_none)] = None,
    status: Annotated[WorklistTaskStatus | None, BeforeValidator(empty_string_to_none)] = None,
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    queue: str | None = None,
) -> HTMLResponse:
    result_queue = queue == "results" or task_type in {
        WorklistTaskType.RESULT_PENDING_ENTRY,
        WorklistTaskType.RESULT_IN_PROGRESS,
        WorklistTaskType.RESULT_CORRECTION_REQUIRED,
    }
    if result_queue:
        if task_type not in {
            WorklistTaskType.RESULT_PENDING_ENTRY,
            WorklistTaskType.RESULT_IN_PROGRESS,
            WorklistTaskType.RESULT_CORRECTION_REQUIRED,
        }:
            task_type = None
        priority = None
        status = None
    response = service.list_tasks(
        task_type=task_type,
        department_id=department_id,
        priority=priority,
        status=status,
        search=search,
        page=page,
        page_size=50,
        group_collection_orders=task_type == WorklistTaskType.ORDER_PENDING_COLLECTION,
        result_tasks_only=result_queue,
    )
    return templates.TemplateResponse(
        request=request,
        name="results/worklist.html",
        context={
            "page_title": "Result entry | บันทึกผลตรวจ" if result_queue else "Laboratory Worklist",
            "result_queue": result_queue,
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
        if item.result:
            existing = item.result
            unchanged = False
            if item.result_type == "NUMERIC":
                with suppress(InvalidOperation):
                    unchanged = Decimal(value) == existing.numeric_value
            elif item.result_type == "TEXT":
                unchanged = " ".join(value.split()) == existing.text_value
            else:
                unchanged = " ".join(value.split()) == existing.categorical_value
            if existing.status == ResultStatus.RELEASED:
                continue
            if (
                unchanged
                and existing.status
                in {
                    ResultStatus.COMPLETED,
                    ResultStatus.VERIFIED,
                    ResultStatus.VERIFICATION_REJECTED,
                    ResultStatus.AMENDMENT_REQUESTED,
                }
                and form.get(f"edit_{key}") != "on"
            ):
                continue
            if unchanged and existing.status in {ResultStatus.COMPLETED, ResultStatus.VERIFIED}:
                continue
        payload: dict[str, object] = {
            "order_item_id": item.id,
            "version": item.result.version if item.result else None,
            "complete": True,
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
            ResultStatus.AMENDMENT_REQUESTED,
        }:
            payload["modification_reason"] = str(form.get(f"reason_{key}", "")).strip()
            if not payload["modification_reason"]:
                raise InvalidResultOperationError("a modification reason is required")
            items.append(ResultEdit.model_validate(payload))
        else:
            items.append(ResultItemSave.model_validate(payload))
    if items:
        service.save_multiple(
            order_id, MultiResultSave(items=items), actor_reference=actor.reference
        )
    return RedirectResponse(
        "/worklist?task_type=RESULT_PENDING_ENTRY&success=results-saved",
        status_code=303,
    )
