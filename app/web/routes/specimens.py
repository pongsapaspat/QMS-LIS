from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.dependencies import SpecimenServiceDependency
from app.core.security import (
    ActorDependency,
    SpecimenCollectorDependency,
    SpecimenReceivingReaderDependency,
)
from app.core.time import parse_local_datetime
from app.domain.exceptions import InvalidSpecimenOperationError, OrderNotFoundError
from app.schemas.specimen import (
    REJECTION_REASON_LABELS,
    RejectionReasonCode,
    SpecimenCollectRequest,
    SpecimenReceiptRequest,
    SpecimenRejectRequest,
)
from app.web.templates import templates

router = APIRouter(prefix="/orders")
receiving_router = APIRouter(prefix="/specimens")


def _errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [str(error["msg"]) for error in exc.errors()]
    return [str(exc)]


@router.get("/{order_id}/specimens", response_class=HTMLResponse, name="specimen_collection")
def specimen_collection(
    order_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> Response:
    requirements = service.requirements(order_id)
    order = service.repository.get_order(order_id)
    if order is None:
        raise OrderNotFoundError("lab order not found")
    return templates.TemplateResponse(
        request=request,
        name="specimens/collection.html",
        context={
            "page_title": "Specimen collection",
            "order": order,
            "requirements": requirements,
            "errors": [],
            "values": {},
        },
    )


@router.post(
    "/{order_id}/specimens/{specimen_type_id}/collect",
    response_class=HTMLResponse,
    name="specimen_collect",
)
async def specimen_collect(
    order_id: int,
    specimen_type_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        "collected_at": form.get("collected_at") or None,
        "collection_note": form.get("collection_note") or None,
    }
    try:
        collected_at = (
            parse_local_datetime(str(values["collected_at"]))
            if values["collected_at"]
            else None
        )
        service.collect(
            SpecimenCollectRequest.model_validate(
                {
                    "order_id": order_id,
                    "specimen_type_id": specimen_type_id,
                    "collected_at": collected_at,
                    "collection_note": values["collection_note"],
                }
            ),
            actor_reference=actor.reference,
        )
    except (
        ValidationError,
        InvalidSpecimenOperationError,
        OrderNotFoundError,
        ValueError,
    ) as exc:
        requirements = service.requirements(order_id)
        order = service.repository.get_order(order_id)
        if order is None:
            raise OrderNotFoundError("lab order not found") from exc
        return templates.TemplateResponse(
            request=request,
            name="specimens/collection.html",
            context={
                "page_title": "Specimen collection",
                "order": order,
                "requirements": requirements,
                "errors": _errors(exc),
                "values": values,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        request.url_for("specimen_collection", order_id=order_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/specimens/{specimen_id}/reject", name="specimen_reject")
async def specimen_reject(
    specimen_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> Response:
    specimen = service.get(specimen_id)
    form = await request.form()
    try:
        service.reject(
            specimen_id,
            SpecimenRejectRequest.model_validate(
                {"rejection_reason": form.get("rejection_reason")}
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, InvalidSpecimenOperationError) as exc:
        requirements = service.requirements(specimen.order_id)
        order = service.repository.get_order(specimen.order_id)
        return templates.TemplateResponse(
            request=request,
            name="specimens/collection.html",
            context={
                "page_title": "Specimen collection",
                "order": order,
                "requirements": requirements,
                "errors": _errors(exc),
                "values": {"rejection_reason": form.get("rejection_reason") or ""},
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        request.url_for("specimen_collection", order_id=specimen.order_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@receiving_router.get("/receiving", response_class=HTMLResponse, name="specimen_receiving_queue")
def specimen_receiving_queue(
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenReceivingReaderDependency,
    status_filter: str = "COLLECTED",
    accession_number: str = "",
    success: str = "",
) -> Response:
    selected_status = None if status_filter == "ALL" else status_filter
    specimens = service.receiving_queue(
        status=selected_status, accession_number=accession_number.strip() or None
    )
    return templates.TemplateResponse(
        request=request,
        name="specimens/receiving_queue.html",
        context={
            "page_title": "Specimen receiving queue",
            "specimens": specimens,
            "status_filter": status_filter,
            "accession_number": accession_number,
            "success": success,
        },
    )


@receiving_router.get(
    "/receiving/{specimen_id}", response_class=HTMLResponse, name="specimen_receiving_detail"
)
def specimen_receiving_detail(
    specimen_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenReceivingReaderDependency,
) -> Response:
    return _receiving_detail_response(request, service.get(specimen_id), actor, {}, [])


@receiving_router.post("/receiving/{specimen_id}/receipt", name="specimen_receive")
async def specimen_receive(
    specimen_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> Response:
    specimen = service.get(specimen_id)
    form = await request.form()
    values = {
        "received_at": form.get("received_at") or None,
        "receiving_note": form.get("receiving_note") or None,
    }
    try:
        received_at = (
            parse_local_datetime(str(values["received_at"]))
            if values["received_at"]
            else None
        )
        service.receive(
            specimen_id,
            SpecimenReceiptRequest.model_validate(
                {"received_at": received_at, "receiving_note": values["receiving_note"]}
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, InvalidSpecimenOperationError, ValueError) as exc:
        return _receiving_detail_response(request, specimen, actor, values, _errors(exc))
    return RedirectResponse(
        f"{request.url_for('specimen_receiving_queue')}?success=received",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@receiving_router.post("/receiving/{specimen_id}/reject", name="specimen_receiving_reject")
async def specimen_receiving_reject(
    specimen_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
) -> Response:
    specimen = service.get(specimen_id)
    form = await request.form()
    values = {
        "rejection_reason_code": form.get("rejection_reason_code") or None,
        "rejection_reason": form.get("rejection_reason") or None,
    }
    try:
        service.reject(
            specimen_id,
            SpecimenRejectRequest.model_validate(values),
            actor_reference=actor.reference,
        )
    except (ValidationError, InvalidSpecimenOperationError) as exc:
        return _receiving_detail_response(request, specimen, actor, values, _errors(exc))
    return RedirectResponse(
        f"{request.url_for('specimen_receiving_queue')}?success=rejected",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _receiving_detail_response(
    request: Request,
    specimen: Any,
    actor: ActorDependency,
    values: dict[str, Any],
    errors: list[str],
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="specimens/receiving_detail.html",
        context={
            "page_title": "Receive specimen",
            "specimen": specimen,
            "reason_labels": REJECTION_REASON_LABELS,
            "reason_codes": RejectionReasonCode,
            "can_mutate": actor.role in {"ADMIN", "LAB_TECH"},
            "errors": errors,
            "values": values,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK,
    )
