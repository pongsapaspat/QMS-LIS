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
from app.domain.collection import CollectionRoom, CollectionRoomFilter
from app.domain.exceptions import InvalidSpecimenOperationError, OrderNotFoundError
from app.schemas.specimen import (
    REJECTION_REASON_LABELS,
    RejectionReasonCode,
    SpecimenCollectRequest,
    SpecimenReceiptRequest,
    SpecimenRejectRequest,
)
from app.web.collection_preferences import remember_collection_room, selected_collection_room
from app.web.templates import templates

router = APIRouter(prefix="/orders")
receiving_router = APIRouter(prefix="/specimens")


def _errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [str(error["msg"]) for error in exc.errors()]
    return [str(exc)]


def _collection_response(
    request: Request, service: SpecimenServiceDependency, order_id: int,
    room: CollectionRoom | None, *, values: dict[str, Any] | None = None,
    errors: list[str] | None = None, status_code: int = 200,
) -> Response:
    order = service.repository.get_order(order_id)
    if order is None:
        raise OrderNotFoundError("lab order not found")
    response = templates.TemplateResponse(
        request=request, name="specimens/collection.html", status_code=status_code,
        context={
            "page_title": "Specimen collection", "order": order,
            "requirements": service.requirements(order_id, collection_room=room),
            "collection_room": room.value if room else "all",
            "errors": errors or [], "values": values or {},
        },
    )
    remember_collection_room(response, room)
    return response


@router.get("/{order_id}/specimens", response_class=HTMLResponse, name="specimen_collection")
def specimen_collection(
    order_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
    collection_room: CollectionRoomFilter | None = None,
) -> Response:
    return _collection_response(
        request, service, order_id, selected_collection_room(request, collection_room)
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
    collection_room: CollectionRoomFilter | None = None,
) -> Response:
    room = selected_collection_room(request, collection_room)
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
                    "collection_group": form.get("collection_group", "INTERNAL"),
                    "replaces_specimen_id": form.get("replaces_specimen_id") or None,
                    "collected_at": collected_at,
                    "collection_note": values["collection_note"],
                }
            ),
            actor_reference=actor.reference,
            collection_room=room,
        )
    except (
        ValidationError,
        InvalidSpecimenOperationError,
        OrderNotFoundError,
        ValueError,
    ) as exc:
        return _collection_response(
            request, service, order_id, room, values=values, errors=_errors(exc),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        f"{request.url_for('specimen_collection', order_id=order_id)}?success=specimen-collected"
        f"&collection_room={room.value if room else 'all'}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/specimens/{specimen_id}/reject", name="specimen_reject")
async def specimen_reject(
    specimen_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: SpecimenCollectorDependency,
    collection_room: CollectionRoomFilter | None = None,
) -> Response:
    specimen = service.get(specimen_id)
    room = selected_collection_room(request, collection_room)
    form = await request.form()
    try:
        if room is not None and not any(
            req.specimen and req.specimen.id == specimen_id
            for req in service.requirements(specimen.order_id, collection_room=room)
        ):
            raise InvalidSpecimenOperationError("สิ่งส่งตรวจนี้ไม่ได้อยู่ในห้องเก็บที่เลือก")
        service.reject(
            specimen_id,
            SpecimenRejectRequest.model_validate(
                {"rejection_reason": form.get("rejection_reason")}
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, InvalidSpecimenOperationError) as exc:
        return _collection_response(
            request, service, specimen.order_id, room, errors=_errors(exc),
            values={"rejection_reason": form.get("rejection_reason") or ""},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        f"{request.url_for('specimen_collection', order_id=specimen.order_id)}"
        f"?success=specimen-rejected&collection_room={room.value if room else 'all'}",
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
        f"{request.url_for('specimen_receiving_queue')}?success=specimen-received&accession={specimen.accession_number}",
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
        f"{request.url_for('specimen_receiving_queue')}?success=specimen-rejected",
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
