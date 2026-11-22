from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import SessionDependency
from app.core.security import Actor, PatientRegistrarDependency
from app.core.time import format_datetime_local, parse_local_datetime, to_app_timezone, utc_now
from app.domain.enums import Sex
from app.domain.exceptions import (
    DuplicatePatientIdentifierError,
    InvalidBookingOperationError,
    PossibleDuplicatePatientError,
)
from app.domain.policies import DuplicateCandidate
from app.models.booking import Booking
from app.models.test_catalog import LabTest
from app.schemas.booking import BookingInput
from app.schemas.patient import PatientCreate
from app.services.booking import STATUS_LABELS, BookingService
from app.services.package import PackageService
from app.services.patient import PatientService
from app.web.routes.patients import _apply_title_choice, _clean_form_data, _form_context
from app.web.templates import templates

router = APIRouter(prefix="/bookings")
FIELDS = tuple(BookingInput.model_fields)


def _form(
    request: Request, session: Session, values: dict[str, Any], *,
    booking: Booking | None = None, errors: list[str] | None = None, code: int = 200,
) -> HTMLResponse:
    tests = [
        test
        for test in session.scalars(
            select(LabTest).where(LabTest.is_active.is_(True)).order_by(LabTest.code)
        )
        if test.department.is_active and test.category.is_active and test.specimen_type.is_active
    ]
    packages = PackageService(session).list(available_only=True)
    active = {("TEST", test.id) for test in tests} | {("PACKAGE", p.id) for p in packages}
    unavailable = (
        [item for item in booking.requested_items if (item["kind"], item["id"]) not in active]
        if booking
        else []
    )
    return templates.TemplateResponse(
        request=request,
        name="bookings/form.html",
        status_code=code,
        context={
            "page_title": "แก้ไขการจอง" if booking else "เพิ่มรายการจอง",
            "values": values,
            "booking": booking,
            "errors": errors or [],
            "tests": tests,
            "packages": packages,
            "unavailable": unavailable,
            "sex_options": Sex,
        },
    )


def _values(booking: Booking) -> dict[str, Any]:
    values = {
        field: getattr(booking, field)
        for field in FIELDS
        if field not in {"test_ids", "package_ids"}
    }
    values["appointment_at"] = format_datetime_local(booking.appointment_at)
    for field, kind in (("test_ids", "TEST"), ("package_ids", "PACKAGE")):
        values[field] = [
            str(item["id"]) for item in booking.requested_items if item["kind"] == kind
        ]
    values["version"] = booking.version
    return values


def _detail(
    request: Request, session: Session, booking: Booking, *,
    errors: list[str] | None = None, code: int = 200, patient_search: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="bookings/detail.html",
        status_code=code,
        context={
            "page_title": booking.booking_number,
            "booking": booking,
            "status_labels": STATUS_LABELS,
            "errors": errors or [],
            "candidates": BookingService(session).candidates(booking, patient_search)
            if booking.status in {"BOOKED", "ARRIVED"}
            else [],
            "patient_search": patient_search or "",
        },
    )


@router.get("", response_class=HTMLResponse, name="booking_list")
def booking_list(
    request: Request,
    session: SessionDependency,
    actor: PatientRegistrarDependency,
    date_from: str = "",
    date_to: str = "",
    status: str = "",
    search: str = "",
    all_dates: bool = False,
    page: int = 1,
) -> HTMLResponse:
    errors = []
    page = max(1, page)
    today = to_app_timezone(utc_now()).date()
    try:
        start = date.fromisoformat(date_from) if date_from else (None if all_dates else today)
        end = date.fromisoformat(date_to) if date_to else (None if all_dates else today)
        bookings, total = BookingService(session).list_bookings(
            date_from=start, date_to=end, status=status or None, search=search, page=page
        )
    except (ValueError, InvalidBookingOperationError) as exc:
        errors = [
            str(exc) if isinstance(exc, InvalidBookingOperationError) else "กรุณาตรวจสอบช่วงวันที่"
        ]
        bookings, total, start, end = [], 0, None, None
    return templates.TemplateResponse(
        request=request,
        name="bookings/list.html",
        status_code=422 if errors else 200,
        context={
            "page_title": "รายการจอง",
            "bookings": bookings,
            "total": total,
            "page": page,
            "date_from": date_from or (start.isoformat() if start else ""),
            "date_to": date_to or (end.isoformat() if end else ""),
            "all_dates": all_dates,
            "status": status,
            "search": search,
            "status_labels": STATUS_LABELS,
            "errors": errors,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="booking_new")
def booking_new(
    request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> HTMLResponse:
    return _form(request, session, {"source": "LINE OA"})


async def _save(
    request: Request, session: Session, actor: Actor, booking: Booking | None = None
) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        field: form.get(field) or None
        for field in FIELDS
        if field not in {"test_ids", "package_ids"}
    }
    values.update(
        test_ids=form.getlist("test_ids"),
        package_ids=form.getlist("package_ids"),
        version=form.get("version"),
    )
    try:
        payload = {key: value for key, value in values.items() if key != "version"}
        payload["appointment_at"] = parse_local_datetime(str(values["appointment_at"] or ""))
        data = BookingInput.model_validate(payload)
        saved = BookingService(session).save(
            data,
            actor.reference,
            booking_id=booking.id if booking else None,
            version=int(str(values["version"])) if booking else None,
        )
    except (ValidationError, ValueError, InvalidBookingOperationError) as exc:
        errors = (
            [error["msg"] for error in exc.errors()]
            if isinstance(exc, ValidationError)
            else [str(exc)]
        )
        return _form(
            request,
            session,
            values,
            booking=booking,
            errors=errors,
            code=409 if getattr(exc, "conflict", False) else 422,
        )
    return RedirectResponse(
        str(request.url_for("booking_detail", booking_id=saved.id)), status_code=303
    )


@router.post("/new", response_model=None)
async def booking_create(
    request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> Response:
    return await _save(request, session, actor)


@router.get("/{booking_id}", response_class=HTMLResponse, name="booking_detail")
def booking_detail(
    booking_id: int,
    request: Request,
    session: SessionDependency,
    actor: PatientRegistrarDependency,
    patient_search: str = "",
) -> HTMLResponse:
    return _detail(
        request, session, BookingService(session).get(booking_id), patient_search=patient_search
    )


@router.get("/{booking_id}/edit", response_class=HTMLResponse, name="booking_edit")
def booking_edit(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> HTMLResponse:
    booking = BookingService(session).get(booking_id)
    if booking.status not in {"BOOKED", "ARRIVED"}:
        return _detail(request, session, booking, errors=["รายการนี้ปิดการแก้ไขแล้ว"], code=409)
    return _form(request, session, _values(booking), booking=booking)


@router.post("/{booking_id}/edit", response_model=None)
async def booking_update(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> Response:
    return await _save(request, session, actor, BookingService(session).get(booking_id))


@router.post("/{booking_id}/status", response_model=None, name="booking_status")
async def booking_status(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> Response:
    form = await request.form()
    service = BookingService(session)
    try:
        service.transition(
            booking_id,
            int(str(form.get("version", "0"))),
            str(form.get("status", "")),
            actor.reference,
        )
    except (ValueError, InvalidBookingOperationError) as exc:
        return _detail(
            request,
            session,
            service.get(booking_id),
            errors=[str(exc)],
            code=409 if getattr(exc, "conflict", False) else 422,
        )
    return RedirectResponse(
        str(request.url_for("booking_detail", booking_id=booking_id)), status_code=303
    )


def _registration(
    request: Request, session: Session, booking: Booking, values: dict[str, Any], *,
    errors: list[str] | None = None, candidates: list[DuplicateCandidate] | None = None,
    code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="patients/form.html",
        status_code=code,
        context=_form_context(
            page_title="ยืนยันลงทะเบียนจากรายการจอง",
            mode="create",
            booking=booking,
            values=values,
            errors=errors or [],
            candidates=candidates or [],
            patient=None,
        ),
    )


@router.get("/{booking_id}/register", response_class=HTMLResponse, name="booking_register")
def booking_register(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> HTMLResponse:
    booking = BookingService(session).get(booking_id)
    if booking.status != "ARRIVED":
        return _detail(
            request, session, booking, errors=["กรุณายืนยันว่าคนไข้มาถึงก่อนลงทะเบียน"], code=409
        )
    values = {
        field: getattr(booking, field)
        for field in (
            "title",
            "first_name_th",
            "last_name_th",
            "sex",
            "phone_number",
            "address",
            "emergency_contact_name",
            "emergency_contact_relationship",
            "emergency_contact_phone",
        )
    }
    return _registration(request, session, booking, values)


@router.post("/{booking_id}/register", response_model=None)
async def booking_register_save(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> Response:
    service = BookingService(session)
    booking = service.get(booking_id)
    form = await request.form()
    values = _clean_form_data(form)
    payload = _apply_title_choice(form, values)
    values["booking_version"] = form.get("booking_version")
    payload["confirm_possible_duplicate"] = form.get("confirm_possible_duplicate") == "true"
    try:
        data = PatientCreate.model_validate(payload)
        service.register_new(
            booking_id, int(str(form.get("booking_version", "0"))), data, actor.reference
        )
    except (
        ValidationError,
        ValueError,
        InvalidBookingOperationError,
        PossibleDuplicatePatientError,
        DuplicatePatientIdentifierError,
    ) as exc:
        errors = (
            [error["msg"] for error in exc.errors()]
            if isinstance(exc, ValidationError)
            else [str(exc)]
        )
        booking = service.get(booking_id)
        if booking.status != "ARRIVED":
            return _detail(request, session, booking, errors=errors, code=409)
        candidates = getattr(exc, "candidates", [])
        if isinstance(exc, DuplicatePatientIdentifierError):
            match = PatientService(session).repository.find_identifier_match(
                national_id=data.national_id, passport_number=data.passport_number
            )
            if match:
                candidates = [PatientService._candidate(match, "exact_identity")]
        return _registration(
            request,
            session,
            booking,
            values,
            errors=errors,
            candidates=candidates,
            code=409
            if isinstance(exc, (PossibleDuplicatePatientError, DuplicatePatientIdentifierError))
            or getattr(exc, "conflict", False)
            else 422,
        )
    return RedirectResponse(f"/orders/new?booking_id={booking_id}", status_code=303)


@router.post("/{booking_id}/link", response_model=None, name="booking_link_patient")
async def booking_link_patient(
    booking_id: int, request: Request, session: SessionDependency, actor: PatientRegistrarDependency
) -> Response:
    service = BookingService(session)
    form = await request.form()
    try:
        service.link_existing(
            booking_id,
            int(str(form.get("version", "0"))),
            int(str(form.get("patient_id", "0"))),
            actor.reference,
            national_id=str(form.get("national_id") or "") or None,
            passport_number=str(form.get("passport_number") or "") or None,
            confirmed=form.get("confirmed") == "on",
        )
    except (ValueError, InvalidBookingOperationError) as exc:
        return _detail(
            request,
            session,
            service.get(booking_id),
            errors=[str(exc)],
            code=409 if getattr(exc, "conflict", False) else 422,
        )
    return RedirectResponse(f"/orders/new?booking_id={booking_id}", status_code=303)
