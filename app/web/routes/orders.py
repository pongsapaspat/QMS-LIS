from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.dependencies import (
    OrderServiceDependency,
    PatientServiceDependency,
    SpecimenServiceDependency,
    TestCatalogServiceDependency,
)
from app.core.security import ActorDependency
from app.domain.exceptions import (
    CatalogNotFoundError,
    PatientNotFoundError,
)
from app.models.order import OrderPriority
from app.schemas.order import LabOrderCreate

router = APIRouter(prefix="/orders")
templates = Jinja2Templates(directory="app/templates")


def _context(
    patient_service: PatientServiceDependency,
    catalog_service: TestCatalogServiceDependency,
    **values: Any,
) -> dict[str, Any]:
    patients, _ = patient_service.list_patients(
        search=None, branch_id=None, include_inactive=False, offset=0, limit=500
    )
    tests, _ = catalog_service.list_tests(
        search=None,
        category_id=None,
        specimen_type_id=None,
        result_type=None,
        is_active=True,
        offset=0,
        limit=500,
    )
    return {"patients": patients, "tests": tests, "priorities": OrderPriority, **values}


@router.get("/new", response_class=HTMLResponse, name="order_new")
def order_new(
    request: Request,
    patient_service: PatientServiceDependency,
    catalog_service: TestCatalogServiceDependency,
    actor: ActorDependency,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="orders/form.html",
        context=_context(
            patient_service,
            catalog_service,
            page_title="New laboratory order",
            values={},
            errors=[],
        ),
    )


@router.post("/new", response_class=HTMLResponse, name="order_create")
async def order_create(
    request: Request,
    order_service: OrderServiceDependency,
    patient_service: PatientServiceDependency,
    catalog_service: TestCatalogServiceDependency,
    actor: ActorDependency,
) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        "patient_id": form.get("patient_id"),
        "test_ids": form.getlist("test_ids"),
        "priority": form.get("priority") or OrderPriority.ROUTINE,
        "clinical_note": form.get("clinical_note") or None,
    }
    try:
        order = order_service.create(
            LabOrderCreate.model_validate(values), actor_reference=actor.reference
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        PatientNotFoundError,
    ) as exc:
        errors = (
            [error["msg"] for error in exc.errors()]
            if isinstance(exc, ValidationError)
            else [str(exc)]
        )
        return templates.TemplateResponse(
            request=request,
            name="orders/form.html",
            context=_context(
                patient_service,
                catalog_service,
                page_title="New laboratory order",
                values=values,
                errors=errors,
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        request.url_for("order_detail", order_id=order.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{order_id}", response_class=HTMLResponse, name="order_detail")
def order_detail(
    order_id: int,
    request: Request,
    service: OrderServiceDependency,
    specimen_service: SpecimenServiceDependency,
    actor: ActorDependency,
) -> Response:
    order = service.get(order_id)
    return templates.TemplateResponse(
        request=request,
        name="orders/detail.html",
        context={
            "page_title": "Laboratory order",
            "order": order,
            "specimens": specimen_service.repository.list_order_specimens(order.id),
        },
    )
