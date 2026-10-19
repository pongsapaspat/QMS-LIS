from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.dependencies import SpecimenServiceDependency
from app.core.security import ActorDependency
from app.domain.exceptions import InvalidSpecimenOperationError, OrderNotFoundError
from app.schemas.specimen import SpecimenCollectRequest, SpecimenRejectRequest

router = APIRouter(prefix="/orders")
templates = Jinja2Templates(directory="app/templates")


def _errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [str(error["msg"]) for error in exc.errors()]
    return [str(exc)]


@router.get("/{order_id}/specimens", response_class=HTMLResponse, name="specimen_collection")
def specimen_collection(
    order_id: int,
    request: Request,
    service: SpecimenServiceDependency,
    actor: ActorDependency,
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
    actor: ActorDependency,
) -> Response:
    form = await request.form()
    values: dict[str, Any] = {"collection_note": form.get("collection_note") or None}
    try:
        service.collect(
            SpecimenCollectRequest.model_validate(
                {"order_id": order_id, "specimen_type_id": specimen_type_id, **values}
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, InvalidSpecimenOperationError, OrderNotFoundError) as exc:
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
    actor: ActorDependency,
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
    except (ValidationError, InvalidSpecimenOperationError):
        return RedirectResponse(
            request.url_for("specimen_collection", order_id=specimen.order_id),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(
        request.url_for("specimen_collection", order_id=specimen.order_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
