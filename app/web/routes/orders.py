from collections import defaultdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.dependencies import (
    OrderServiceDependency,
    PatientServiceDependency,
    SpecimenServiceDependency,
    TestCatalogServiceDependency,
)
from app.core.config import get_settings
from app.core.security import ActorDependency
from app.core.time import app_date_range_utc, to_app_timezone, utc_now
from app.domain.exceptions import (
    CatalogNotFoundError,
    InvalidBookingOperationError,
    PatientNotFoundError,
)
from app.models.order import OrderStatus
from app.models.specimen import Specimen
from app.schemas.order import LabOrderCreate
from app.services.booking import BookingService
from app.services.order_progress import ORDER_STATUS_LABELS, summarize_order
from app.services.package import PackageService
from app.services.report_identity import capture_identity, order_creator_label
from app.web.templates import templates

router = APIRouter(prefix="/orders")
ORDER_VIEW_ROLES = {"ADMIN", "IT", "RECEPTION", "LAB_TECH", "LAB_SUPERVISOR"}


@router.get("", response_class=HTMLResponse, name="order_list")
def order_list(
    request: Request,
    service: OrderServiceDependency,
    actor: ActorDependency,
    search: Annotated[str, Query(max_length=100)] = "",
    order_status: str = "",
    date_from: str = "",
    date_to: str = "",
    all_dates: bool = False,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
) -> Response:
    if actor.role not in ORDER_VIEW_ROLES:
        raise HTTPException(403, "Order viewing permission required")
    today_and_open = not (all_dates or date_from or date_to)
    page_size = 25
    errors = []
    rows: list[dict[str, Any]] = []
    total = 0
    try:
        today = to_app_timezone(utc_now()).date() if today_and_open else None
        first = date.fromisoformat(date_from) if date_from else today
        last = date.fromisoformat(date_to) if date_to else today
        if first and last and first > last:
            raise ValueError
        start, end = app_date_range_utc(first, last)
    except (ValueError, OverflowError):
        errors.append("กรุณาตรวจสอบช่วงวันที่")
        start, end = None, None
    try:
        selected_status = OrderStatus(order_status) if order_status else None
    except ValueError:
        errors.append("สถานะคำสั่งตรวจไม่ถูกต้อง")
        selected_status = None
    if not errors:
        orders, total = service.repository.list_orders(
            search=search, status=selected_status, start=start, end=end,
            include_older_open=today_and_open, offset=(page - 1) * page_size, limit=page_size,
        )
        specimens: dict[int, list[Specimen]] = defaultdict(list)
        for specimen in service.repository.current_specimens([order.id for order in orders]):
            specimens[specimen.order_id].append(specimen)
        rows = [
            {"order": order, "progress": summarize_order(order, specimens[order.id])}
            for order in orders
        ]
    return templates.TemplateResponse(
        request=request,
        name="orders/list.html",
        status_code=422 if errors else 200,
        context={
            "page_title": "รายการ Order", "rows": rows, "total": total, "page": page,
            "has_next": page * page_size < total, "errors": errors,
            "statuses": ORDER_STATUS_LABELS, "search": search, "order_status": order_status,
            "date_from": date_from, "date_to": date_to, "all_dates": all_dates,
            "today_and_open": today_and_open, "show_lab_details": actor.role != "RECEPTION",
        },
    )


def _context(
    patient_service: PatientServiceDependency,
    catalog_service: TestCatalogServiceDependency,
    **values: Any,
) -> dict[str, Any]:
    tests, _ = catalog_service.list_tests(
        search=None,
        category_id=None,
        department_id=None,
        specimen_type_id=None,
        result_type=None,
        is_active=True,
        offset=0,
        limit=500,
    )
    packages = PackageService(catalog_service.session).list(available_only=True)
    tests = [test for test in tests if test.department.is_active]
    booking = values.get("booking")
    available = {("TEST", t.id) for t in tests} | {("PACKAGE", p.id) for p in packages}
    return {
        "packages": packages,
        "tests": tests,
        "unavailable_booking_items": [
            item for item in booking.requested_items if (item["kind"], item["id"]) not in available
        ]
        if booking
        else [],
        **values,
    }


@router.get("/new", response_class=HTMLResponse, name="order_new")
def order_new(
    request: Request,
    patient_service: PatientServiceDependency,
    catalog_service: TestCatalogServiceDependency,
    actor: ActorDependency,
    booking_id: int | None = None,
) -> Response:
    booking = None
    values = {}
    patient = None
    if booking_id is not None:
        if actor.role not in {"ADMIN", "IT", "RECEPTION"}:
            raise HTTPException(403, "Booking access requires reception permission")
        booking = BookingService(patient_service.session).get(booking_id)
        if booking.order_id:
            return RedirectResponse(
                str(request.url_for("order_detail", order_id=booking.order_id)), status_code=303
            )
        if booking.status != "REGISTERED" or not booking.patient_id:
            return RedirectResponse(
                str(request.url_for("booking_detail", booking_id=booking.id)), status_code=303
            )
        patient = patient_service.get(booking.patient_id)
        values = {
            "booking_id": booking.id,
            "patient_id": patient.id,
            "test_ids": [
                str(item["id"]) for item in booking.requested_items if item["kind"] == "TEST"
            ],
            "package_ids": [
                str(item["id"]) for item in booking.requested_items if item["kind"] == "PACKAGE"
            ],
        }
    return templates.TemplateResponse(
        request=request,
        name="orders/form.html",
        context=_context(
            patient_service,
            catalog_service,
            page_title="New laboratory order",
            values=values,
            selected_patient=patient,
            booking=booking,
            errors=[],
            creator_preview=capture_identity(
                patient_service.session, actor.reference, get_settings()
            ),
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
        "booking_id": form.get("booking_id") or None,
        "test_ids": form.getlist("test_ids"),
        "package_ids": form.getlist("package_ids"),
        "clinical_note": form.get("clinical_note") or None,
        "referrer_name": form.get("referrer_name"),
        "referrer_organization": form.get("referrer_organization"),
        "referrer_license_type": form.get("referrer_license_type"),
        "referrer_license_number": form.get("referrer_license_number"),
    }
    if values["booking_id"] and actor.role not in {"ADMIN", "IT", "RECEPTION"}:
        raise HTTPException(403, "Booking access requires reception permission")
    try:
        order = order_service.create(
            LabOrderCreate.model_validate(values), actor_reference=actor.reference
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        PatientNotFoundError,
        InvalidBookingOperationError,
    ) as exc:
        errors = (
            [error["msg"] for error in exc.errors()]
            if isinstance(exc, ValidationError)
            else [str(exc)]
        )
        selected_patient = None
        try:
            if values["patient_id"]:
                selected_patient = patient_service.get(int(values["patient_id"]))
        except (ValueError, PatientNotFoundError):
            pass
        return templates.TemplateResponse(
            request=request,
            name="orders/form.html",
            context=_context(
                patient_service,
                catalog_service,
                page_title="New laboratory order",
                values=values,
                selected_patient=selected_patient,
                booking=(
                    BookingService(patient_service.session).get(int(str(values["booking_id"])))
                    if str(values.get("booking_id") or "").isdigit()
                    else None
                ),
                errors=errors,
                creator_preview=capture_identity(
                    patient_service.session, actor.reference, get_settings()
                ),
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        (
            f"{request.url_for('order_detail', order_id=order.id)}"
            f"?success=order-created&order_number={order.order_number}"
        ),
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
    if actor.role not in ORDER_VIEW_ROLES:
        raise HTTPException(403, "Order viewing permission required")
    order = service.get(order_id)
    specimens = specimen_service.repository.list_order_specimens(order.id)
    progress = summarize_order(order, specimens)
    active = order.status not in {OrderStatus.CANCELLED, OrderStatus.RELEASED}
    can_collect = actor.role in {"ADMIN", "LAB_TECH", "IT"}
    return templates.TemplateResponse(
        request=request,
        name="orders/detail.html",
        context={
            "page_title": "Laboratory order",
            "order": order,
            "order_creator_label": order_creator_label(order),
            "specimens": specimens,
            "can_collect_specimens": active and can_collect,
            "can_enter_results": active and can_collect and progress.can_enter_results,
            "can_receive": active and can_collect,
            "can_verify": active and bool(progress.awaiting_verification)
            and actor.role in {"ADMIN", "LAB_SUPERVISOR", "IT"},
            "can_release": order.status == OrderStatus.RESULTS_VERIFIED
            and actor.role in {"ADMIN", "LAB_SUPERVISOR", "IT"},
            "can_read_report": actor.role != "RECEPTION" and order.status == OrderStatus.RELEASED,
            "show_lab_details": actor.role != "RECEPTION",
            "progress": progress,
            "statuses": ORDER_STATUS_LABELS,
        },
    )
