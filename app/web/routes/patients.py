from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.dependencies import PatientServiceDependency
from app.core.security import PatientRegistrarDependency
from app.domain.enums import BloodGroup, Sex
from app.domain.exceptions import (
    DuplicatePatientIdentifierError,
    InvalidPatientChangeError,
    PossibleDuplicatePatientError,
)
from app.models.patient import Patient
from app.schemas.patient import PatientCreate, PatientUpdate
from app.web.templates import templates

router = APIRouter(prefix="/patients")

PATIENT_FORM_FIELDS = (
    "title",
    "first_name_th",
    "last_name_th",
    "first_name_en",
    "last_name_en",
    "date_of_birth",
    "sex",
    "national_id",
    "passport_number",
    "phone_number",
    "address",
    "email",
    "blood_group",
    "emergency_contact_name",
    "emergency_contact_relationship",
    "emergency_contact_phone",
)

RECEPTION_EDITABLE_FIELDS = (
    "title",
    "first_name_th",
    "last_name_th",
    "first_name_en",
    "last_name_en",
    "date_of_birth",
    "sex",
    "phone_number",
    "address",
    "email",
    "emergency_contact_name",
    "emergency_contact_relationship",
    "emergency_contact_phone",
)


def _form_context(**values: Any) -> dict[str, Any]:
    return {
        "sex_options": Sex,
        "blood_group_options": BloodGroup,
        "restrict_registration_fields": False,
        "lock_national_id": False,
        "lock_passport_number": False,
        **values,
    }


def _clean_form_data(
    form: Any, fields: tuple[str, ...] = PATIENT_FORM_FIELDS
) -> dict[str, Any]:
    return {field: form.get(field) or None for field in fields}


def _apply_title_choice(form: Any, values: dict[str, Any]) -> dict[str, Any]:
    title_option = str(form.get("title_option") or "")
    custom_title = str(form.get("title_custom") or "").strip() or None
    values["title_option"] = title_option
    values["title_custom"] = custom_title or ""
    values["title"] = custom_title if title_option == "__OTHER__" else title_option or None
    return {
        key: value
        for key, value in values.items()
        if key not in {"title_option", "title_custom"}
    }


def _patient_values(patient: Patient) -> dict[str, Any]:
    values = {field: getattr(patient, field) for field in PATIENT_FORM_FIELDS}
    if patient.date_of_birth is not None:
        values["date_of_birth"] = patient.date_of_birth.isoformat()
    return values


def _validation_messages(exc: ValidationError) -> list[str]:
    return [error["msg"] for error in exc.errors()]


@router.get("", response_class=HTMLResponse, name="patient_list")
def patient_list(
    request: Request,
    service: PatientServiceDependency,
    actor: PatientRegistrarDependency,
    search: str | None = None,
    page: int = 1,
    created_id: int | None = None,
) -> HTMLResponse:
    page = max(page, 1)
    page_size = 20
    patients, total = service.list_patients(
        search=search,
        branch_id=None,
        include_inactive=True,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="patients/list.html",
        context={
            "page_title": "Patients | ผู้ป่วย",
            "patients": patients,
            "search": search or "",
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_previous": page > 1,
            "has_next": page * page_size < total,
            "created_id": created_id,
        },
    )


@router.get("/new", response_class=HTMLResponse, name="patient_new")
def patient_new_form(request: Request, actor: PatientRegistrarDependency) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="patients/form.html",
        context=_form_context(
            page_title="New patient | ลงทะเบียนผู้ป่วย",
            mode="create",
            values={},
            errors=[],
            candidates=[],
            patient=None,
        ),
    )


@router.post("/new", response_class=HTMLResponse)
async def patient_create_from_form(
    request: Request,
    service: PatientServiceDependency,
    actor: PatientRegistrarDependency,
) -> Response:
    form = await request.form()
    values = _clean_form_data(form)
    data_values = _apply_title_choice(form, values)
    values["branch_id"] = 1
    data_values["branch_id"] = 1
    values["confirm_possible_duplicate"] = form.get("confirm_possible_duplicate") == "true"
    data_values["confirm_possible_duplicate"] = values["confirm_possible_duplicate"]
    if not values.get("national_id"):
        return templates.TemplateResponse(
            request=request,
            name="patients/form.html",
            context=_form_context(
                page_title="New patient | ลงทะเบียนผู้ป่วย",
                mode="create",
                values=values,
                errors=["Thai National ID is required and must contain 13 digits"],
                candidates=[],
                patient=None,
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    try:
        data = PatientCreate.model_validate(data_values)
        patient = service.create(data, actor_reference=actor.reference)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request=request,
            name="patients/form.html",
            context=_form_context(
                page_title="New patient | ลงทะเบียนผู้ป่วย",
                mode="create",
                values=values,
                errors=_validation_messages(exc),
                candidates=[],
                patient=None,
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    except PossibleDuplicatePatientError as exc:
        return templates.TemplateResponse(
            request=request,
            name="patients/form.html",
            context=_form_context(
                page_title="Review possible duplicate | ตรวจสอบข้อมูลซ้ำ",
                mode="create",
                values=values,
                errors=[str(exc)],
                candidates=exc.candidates,
                patient=None,
            ),
            status_code=status.HTTP_409_CONFLICT,
        )
    except DuplicatePatientIdentifierError as exc:
        return templates.TemplateResponse(
            request=request,
            name="patients/form.html",
            context=_form_context(
                page_title="New patient | ลงทะเบียนผู้ป่วย",
                mode="create",
                values=values,
                errors=[str(exc)],
                candidates=[],
                patient=None,
            ),
            status_code=status.HTTP_409_CONFLICT,
        )
    return RedirectResponse(
        f"{request.url_for('patient_list')}?success=patient-created&created_id={patient.id}&hn={patient.hn}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/{patient_id}", response_class=HTMLResponse, name="patient_detail")
def patient_detail(
    patient_id: int,
    request: Request,
    service: PatientServiceDependency,
    actor: PatientRegistrarDependency,
) -> HTMLResponse:
    patient = service.get(patient_id)
    return templates.TemplateResponse(
        request=request,
        name="patients/detail.html",
        context={"page_title": patient.hn, "patient": patient},
    )


@router.get("/{patient_id}/edit", response_class=HTMLResponse, name="patient_edit")
def patient_edit_form(
    patient_id: int,
    request: Request,
    service: PatientServiceDependency,
    actor: PatientRegistrarDependency,
) -> HTMLResponse:
    patient = service.get(patient_id)
    return templates.TemplateResponse(
        request=request,
        name="patients/form.html",
        context=_form_context(
            page_title=f"Edit {patient.hn} | แก้ไขข้อมูล",
            mode="edit",
            values=_patient_values(patient),
            errors=[],
            candidates=[],
            patient=patient,
            restrict_registration_fields=actor.role == "RECEPTION",
            lock_national_id=actor.role == "RECEPTION" and patient.national_id is not None,
            lock_passport_number=(
                actor.role == "RECEPTION" and patient.passport_number is not None
            ),
        ),
    )


@router.post("/{patient_id}/edit", response_class=HTMLResponse)
async def patient_update_from_form(
    patient_id: int,
    request: Request,
    service: PatientServiceDependency,
    actor: PatientRegistrarDependency,
) -> Response:
    patient = service.get(patient_id)
    form = await request.form()
    if actor.role == "RECEPTION":
        reception_fields = list(RECEPTION_EDITABLE_FIELDS)
        if patient.national_id is None:
            reception_fields.append("national_id")
        if patient.passport_number is None:
            reception_fields.append("passport_number")
        editable_fields = tuple(reception_fields)
    else:
        editable_fields = PATIENT_FORM_FIELDS
    values = _clean_form_data(form, editable_fields)
    data_values = _apply_title_choice(form, values)
    values["change_reason"] = form.get("change_reason") or ""
    data_values["change_reason"] = values["change_reason"]
    if actor.role != "RECEPTION":
        values["is_active"] = form.get("is_active") == "on"
        data_values["is_active"] = values["is_active"]
    try:
        data = PatientUpdate.model_validate(data_values)
        service.update(patient_id, data, actor_reference=actor.reference)
    except (ValidationError, InvalidPatientChangeError, DuplicatePatientIdentifierError) as exc:
        errors = _validation_messages(exc) if isinstance(exc, ValidationError) else [str(exc)]
        rendered_values = _patient_values(patient)
        rendered_values.update(values)
        return templates.TemplateResponse(
            request=request,
            name="patients/form.html",
            context=_form_context(
                page_title=f"Edit {patient.hn} | แก้ไขข้อมูล",
                mode="edit",
                values=rendered_values,
                errors=errors,
                candidates=[],
                patient=patient,
                restrict_registration_fields=actor.role == "RECEPTION",
                lock_national_id=(
                    actor.role == "RECEPTION" and patient.national_id is not None
                ),
                lock_passport_number=(
                    actor.role == "RECEPTION" and patient.passport_number is not None
                ),
            ),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return RedirectResponse(
        f"{request.url_for('patient_detail', patient_id=patient_id)}?success=patient-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )
