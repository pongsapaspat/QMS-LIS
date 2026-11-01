import json
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.dependencies import TestCatalogServiceDependency
from app.core.security import AdminActorDependency
from app.domain.enums import ResultType
from app.domain.exceptions import (
    CatalogNotFoundError,
    DuplicateCatalogCodeError,
    InvalidCatalogOperationError,
)
from app.schemas.test_catalog import (
    ActivationRequest,
    CatalogTestCreate,
    CatalogTestUpdate,
    ConfigurationCreate,
    ConfigurationUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    QualitativeOptionCreate,
    QualitativeOptionUpdate,
    ReferenceRangeCreate,
    ReferenceRangeUpdate,
)
from app.web.templates import templates

router = APIRouter(prefix="/test-catalog")

TEST_FORM_FIELDS = (
    "code",
    "name_th",
    "name_en",
    "category_id",
    "department_id",
    "specimen_type_id",
    "current_price",
    "result_type",
    "result_unit",
    "tat_minutes",
    "reason",
)
RANGE_FORM_FIELDS = (
    "sex",
    "minimum_age",
    "maximum_age",
    "age_unit",
    "lower_value",
    "upper_value",
    "lower_critical",
    "upper_critical",
    "display_text",
    "context_metadata",
    "reason",
)
OPTION_FORM_FIELDS = ("code", "label_th", "label_en", "sort_order", "is_abnormal", "reason")


def _form_value(form: Any, field: str) -> str | None:
    value = form.get(field)
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _form_values(form: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: _form_value(form, field) for field in fields}


def _checkbox(form: Any, field: str) -> bool:
    return form.get(field) in {"on", "true", "1", "yes"}


def _validation_messages(exc: ValidationError) -> list[str]:
    return [str(error["msg"]) for error in exc.errors()]


def _catalog_errors(exc: Exception) -> list[str]:
    return _validation_messages(exc) if isinstance(exc, ValidationError) else [str(exc)]


def _config_values(entity: Any | None) -> dict[str, Any]:
    if entity is None:
        return {"name_th": "", "name_en": "", "code": "", "is_active": True}
    return {
        "code": entity.code,
        "name_th": entity.name_th,
        "name_en": entity.name_en,
        "is_active": entity.is_active,
    }


def _detail_context(service: Any, test_id: int) -> dict[str, Any]:
    test = service.get_test(test_id)
    return {
        "test": test,
        "reference_ranges": service.list_reference_ranges(test_id),
        "qualitative_options": service.list_qualitative_options(test_id),
        "price_history": service.list_price_history(test_id),
        "audit_history": service.list_test_audit_history(test_id),
    }


def _master_context(
    service: Any, test: Any | None = None, *, include_inactive_departments: bool = False
) -> dict[str, Any]:
    categories = service.list_categories()
    department_rows, _ = service.list_departments(
        is_active=None if include_inactive_departments else True
    )
    departments = [item for item, _ in department_rows]
    specimen_types = service.list_specimen_types()
    if test is not None:
        if not test.category.is_active:
            categories.append(test.category)
        if not test.department.is_active:
            departments.append(test.department)
        if not test.specimen_type.is_active:
            specimen_types.append(test.specimen_type)
    return {
        "categories": categories,
        "departments": departments,
        "specimen_types": specimen_types,
    }


def _parse_context_metadata(values: dict[str, Any]) -> None:
    raw = values.get("context_metadata")
    if raw:
        with suppress(json.JSONDecodeError):
            values["context_metadata"] = json.loads(raw)


def _render_form_error(
    request: Request,
    template: str,
    context: dict[str, Any],
    exc: Exception,
) -> Response:
    context["errors"] = _catalog_errors(exc)
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=context,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


@router.get("", response_class=HTMLResponse, name="test_catalog_list")
def test_catalog_list(
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
    search: str | None = None,
    category_id: int | None = None,
    department_id: int | None = None,
    specimen_type_id: int | None = None,
    result_type: ResultType | None = None,
    is_active: str | None = "true",
    page: int = 1,
) -> Response:
    page = max(page, 1)
    page_size = 20
    active_filter = None if is_active in {None, "all", ""} else is_active == "true"
    tests, total = service.list_tests(
        search=search,
        category_id=category_id,
        department_id=department_id,
        specimen_type_id=specimen_type_id,
        result_type=result_type.value if result_type else None,
        is_active=active_filter,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/list.html",
        context={
            "page_title": "Test Catalog",
            "tests": tests,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_previous": page > 1,
            "has_next": page * page_size < total,
            "search": search or "",
            "category_id": category_id,
            "department_id": department_id,
            "specimen_type_id": specimen_type_id,
            "result_type": result_type.value if result_type else "",
            "is_active": is_active or "all",
            "result_types": ResultType,
            **_master_context(service, include_inactive_departments=True),
        },
    )


@router.get("/new", response_class=HTMLResponse, name="test_catalog_new")
def test_catalog_new(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/form.html",
        context={
            "page_title": "Test Catalog",
            "mode": "create",
            "values": {"result_type": ResultType.NUMERIC.value},
            "errors": [],
            "test": None,
            **_master_context(service),
        },
    )


@router.post("/new", response_class=HTMLResponse, name="test_catalog_create")
async def test_catalog_create(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    form = await request.form()
    values = _form_values(form, TEST_FORM_FIELDS)
    try:
        test = service.create_test(
            CatalogTestCreate.model_validate(values), actor_reference=actor.reference
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        DuplicateCatalogCodeError,
        InvalidCatalogOperationError,
    ) as exc:
        return _render_form_error(
            request,
            "test_catalog/form.html",
            {
                "page_title": "Test Catalog",
                "mode": "create",
                "values": values,
                "test": None,
                **_master_context(service),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/categories", response_class=HTMLResponse, name="test_catalog_categories")
def test_catalog_categories(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration.html",
        context={
            "page_title": "Test Catalog",
            "kind": "category",
            "items": service.list_categories(include_inactive=True),
            "new_url": request.url_for("test_catalog_category_new"),
        },
    )


@router.get("/categories/new", response_class=HTMLResponse, name="test_catalog_category_new")
def test_catalog_category_new(request: Request, actor: AdminActorDependency) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration_form.html",
        context={
            "page_title": "Test Catalog",
            "kind": "category",
            "mode": "create",
            "values": _config_values(None),
            "errors": [],
            "form_action": request.url_for("test_catalog_category_create"),
        },
    )


@router.post("/categories/new", response_class=HTMLResponse, name="test_catalog_category_create")
async def test_catalog_category_create(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    form = await request.form()
    values = _form_values(form, ("code", "name_th", "name_en", "reason"))
    try:
        service.create_category(
            ConfigurationCreate.model_validate(values), actor_reference=actor.reference
        )
    except (ValidationError, DuplicateCatalogCodeError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/configuration_form.html",
            {
                "page_title": "Test Catalog",
                "kind": "category",
                "mode": "create",
                "values": values,
                "form_action": request.url_for("test_catalog_category_create"),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_categories"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get(
    "/categories/{category_id}/edit", response_class=HTMLResponse, name="test_catalog_category_edit"
)
def test_catalog_category_edit(
    category_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    category = service.repository.get_category(category_id)
    if category is None:
        raise CatalogNotFoundError("test category not found")
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration_form.html",
        context={
            "page_title": "Test Catalog",
            "kind": "category",
            "mode": "edit",
            "values": _config_values(category),
            "errors": [],
            "form_action": request.url_for("test_catalog_category_update", category_id=category_id),
        },
    )


@router.post(
    "/categories/{category_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_category_update",
)
async def test_catalog_category_update(
    category_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    values = _form_values(form, ("name_th", "name_en", "reason"))
    values["is_active"] = _checkbox(form, "is_active")
    try:
        service.update_category(
            category_id, ConfigurationUpdate.model_validate(values), actor_reference=actor.reference
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/configuration_form.html",
            {
                "page_title": "Test Catalog",
                "kind": "category",
                "mode": "edit",
                "values": values,
                "form_action": request.url_for(
                    "test_catalog_category_update", category_id=category_id
                ),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_categories"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/specimen-types", response_class=HTMLResponse, name="test_catalog_specimens")
def test_catalog_specimens(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration.html",
        context={
            "page_title": "Test Catalog",
            "kind": "specimen",
            "items": service.list_specimen_types(include_inactive=True),
            "new_url": request.url_for("test_catalog_specimen_new"),
        },
    )


@router.get("/specimen-types/new", response_class=HTMLResponse, name="test_catalog_specimen_new")
def test_catalog_specimen_new(request: Request, actor: AdminActorDependency) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration_form.html",
        context={
            "page_title": "Test Catalog",
            "kind": "specimen",
            "mode": "create",
            "values": _config_values(None),
            "errors": [],
            "form_action": request.url_for("test_catalog_specimen_create"),
        },
    )


@router.post(
    "/specimen-types/new", response_class=HTMLResponse, name="test_catalog_specimen_create"
)
async def test_catalog_specimen_create(
    request: Request, service: TestCatalogServiceDependency, actor: AdminActorDependency
) -> Response:
    form = await request.form()
    values = _form_values(form, ("code", "name_th", "name_en", "reason"))
    try:
        service.create_specimen_type(
            ConfigurationCreate.model_validate(values), actor_reference=actor.reference
        )
    except (ValidationError, DuplicateCatalogCodeError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/configuration_form.html",
            {
                "page_title": "Test Catalog",
                "kind": "specimen",
                "mode": "create",
                "values": values,
                "form_action": request.url_for("test_catalog_specimen_create"),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_specimens"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/departments", response_class=HTMLResponse, name="test_catalog_departments")
def test_catalog_departments(
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
    search: str | None = None,
    is_active: str | None = "all",
    page: int = 1,
) -> Response:
    page = max(page, 1)
    page_size = 25
    active_filter = None if is_active in {None, "all", ""} else is_active == "true"
    rows, total = service.list_departments(
        search=search,
        is_active=active_filter,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/departments.html",
        context={
            "page_title": "Laboratory Departments",
            "rows": rows,
            "search": search or "",
            "is_active": is_active or "all",
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_previous": page > 1,
            "has_next": page * page_size < total,
            "errors": [],
        },
    )


@router.get("/departments/new", response_class=HTMLResponse, name="test_catalog_department_new")
def test_catalog_department_new(request: Request, actor: AdminActorDependency) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/department_form.html",
        context={
            "page_title": "New Laboratory Department",
            "mode": "create",
            "values": _config_values(None),
            "errors": [],
            "form_action": request.url_for("test_catalog_department_create"),
        },
    )


@router.post("/departments/new", response_class=HTMLResponse, name="test_catalog_department_create")
async def test_catalog_department_create(
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    values = _form_values(form, ("code", "name_th", "name_en", "reason"))
    values["is_active"] = _checkbox(form, "is_active")
    try:
        department = service.create_department(
            DepartmentCreate.model_validate(values), actor_reference=actor.reference
        )
    except (ValidationError, DuplicateCatalogCodeError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/department_form.html",
            {
                "page_title": "New Laboratory Department",
                "mode": "create",
                "values": values,
                "form_action": request.url_for("test_catalog_department_create"),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_department_detail", department_id=department.id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/departments/{department_id}",
    response_class=HTMLResponse,
    name="test_catalog_department_detail",
)
def test_catalog_department_detail(
    department_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    department = service.get_department(department_id)
    tests = service.list_department_tests(department_id)
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/department_detail.html",
        context={
            "page_title": "Laboratory Department",
            "department": department,
            "tests": tests,
            "test_count": len(tests),
            "errors": [],
        },
    )


@router.get(
    "/departments/{department_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_department_edit",
)
def test_catalog_department_edit(
    department_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    department = service.get_department(department_id)
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/department_form.html",
        context={
            "page_title": "Edit Laboratory Department",
            "mode": "edit",
            "values": _config_values(department),
            "errors": [],
            "form_action": request.url_for(
                "test_catalog_department_update", department_id=department_id
            ),
        },
    )


@router.post(
    "/departments/{department_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_department_update",
)
async def test_catalog_department_update(
    department_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    values = _form_values(form, ("code", "name_th", "name_en", "reason"))
    try:
        service.update_department(
            department_id,
            DepartmentUpdate.model_validate(values),
            actor_reference=actor.reference,
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        DuplicateCatalogCodeError,
        InvalidCatalogOperationError,
    ) as exc:
        return _render_form_error(
            request,
            "test_catalog/department_form.html",
            {
                "page_title": "Edit Laboratory Department",
                "mode": "edit",
                "values": values,
                "form_action": request.url_for(
                    "test_catalog_department_update", department_id=department_id
                ),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_department_detail", department_id=department_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/departments/{department_id}/activation",
    response_class=HTMLResponse,
    name="test_catalog_department_activation",
)
async def test_catalog_department_activation(
    department_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    try:
        service.set_department_activation(
            department_id,
            ActivationRequest(
                is_active=_checkbox(form, "is_active"),
                reason=_form_value(form, "reason") or "",
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        department = service.get_department(department_id)
        tests = service.list_department_tests(department_id)
        return _render_form_error(
            request,
            "test_catalog/department_detail.html",
            {
                "page_title": "Laboratory Department",
                "department": department,
                "tests": tests,
                "test_count": len(tests),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_department_detail", department_id=department_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/specimen-types/{specimen_type_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_specimen_edit",
)
def test_catalog_specimen_edit(
    specimen_type_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    specimen = service.repository.get_specimen_type(specimen_type_id)
    if specimen is None:
        raise CatalogNotFoundError("specimen type not found")
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/configuration_form.html",
        context={
            "page_title": "Test Catalog",
            "kind": "specimen",
            "mode": "edit",
            "values": _config_values(specimen),
            "errors": [],
            "form_action": request.url_for(
                "test_catalog_specimen_update", specimen_type_id=specimen_type_id
            ),
        },
    )


@router.post(
    "/specimen-types/{specimen_type_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_specimen_update",
)
async def test_catalog_specimen_update(
    specimen_type_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    values = _form_values(form, ("name_th", "name_en", "reason"))
    values["is_active"] = _checkbox(form, "is_active")
    try:
        service.update_specimen_type(
            specimen_type_id,
            ConfigurationUpdate.model_validate(values),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/configuration_form.html",
            {
                "page_title": "Test Catalog",
                "kind": "specimen",
                "mode": "edit",
                "values": values,
                "form_action": request.url_for(
                    "test_catalog_specimen_update", specimen_type_id=specimen_type_id
                ),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_specimens"), status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/{test_id}", response_class=HTMLResponse, name="test_catalog_detail")
def test_catalog_detail(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    context = _detail_context(service, test_id)
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/detail.html",
        context={
            "page_title": "Test Catalog",
            **context,
        },
    )


@router.get("/{test_id}/edit", response_class=HTMLResponse, name="test_catalog_edit")
def test_catalog_edit(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    values = {field: getattr(test, field) for field in TEST_FORM_FIELDS if field != "reason"}
    values.update(
        {
            "category_id": str(test.category_id),
            "department_id": str(test.department_id),
            "specimen_type_id": str(test.specimen_type_id),
            "result_type": str(test.result_type),
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/form.html",
        context={
            "page_title": "Test Catalog",
            "mode": "edit",
            "values": values,
            "errors": [],
            "test": test,
            **_master_context(service, test),
        },
    )


@router.post("/{test_id}/edit", response_class=HTMLResponse, name="test_catalog_update")
async def test_catalog_update(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    form = await request.form()
    values = _form_values(form, TEST_FORM_FIELDS)
    try:
        service.update_test(
            test_id, CatalogTestUpdate.model_validate(values), actor_reference=actor.reference
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        DuplicateCatalogCodeError,
        InvalidCatalogOperationError,
    ) as exc:
        return _render_form_error(
            request,
            "test_catalog/form.html",
            {
                "page_title": "Test Catalog",
                "mode": "edit",
                "values": values,
                "test": test,
                **_master_context(service, test),
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/{test_id}/activation", response_class=HTMLResponse, name="test_catalog_activation")
async def test_catalog_activation(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    try:
        service.set_test_activation(
            test_id,
            ActivationRequest(
                is_active=_checkbox(form, "is_active"), reason=_form_value(form, "reason") or ""
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/detail.html",
            {"page_title": "Test Catalog", **_detail_context(service, test_id)},
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/{test_id}/reference-ranges/new", response_class=HTMLResponse, name="test_catalog_range_new"
)
def test_catalog_range_new(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/range_form.html",
        context={
            "page_title": "Test Catalog",
            "test": test,
            "mode": "create",
            "values": {"sex": "ALL", "age_unit": "YEARS", "is_active": True},
            "errors": [],
            "range": None,
        },
    )


@router.post(
    "/{test_id}/reference-ranges/new", response_class=HTMLResponse, name="test_catalog_range_create"
)
async def test_catalog_range_create(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    form = await request.form()
    values = _form_values(form, RANGE_FORM_FIELDS)
    _parse_context_metadata(values)
    try:
        service.create_reference_range(
            test_id, ReferenceRangeCreate.model_validate(values), actor_reference=actor.reference
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/range_form.html",
            {
                "page_title": "Test Catalog",
                "test": test,
                "mode": "create",
                "values": values,
                "range": None,
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/{test_id}/reference-ranges/{range_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_range_edit",
)
def test_catalog_range_edit(
    test_id: int,
    range_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    reference_range = service.repository.get_reference_range(range_id)
    if reference_range is None or reference_range.test_id != test_id:
        raise CatalogNotFoundError("reference range not found")
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/range_form.html",
        context={
            "page_title": "Test Catalog",
            "test": test,
            "mode": "edit",
            "values": {
                field: getattr(reference_range, field)
                for field in RANGE_FORM_FIELDS
                if field != "reason"
            },
            "errors": [],
            "range": reference_range,
        },
    )


@router.post(
    "/{test_id}/reference-ranges/{range_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_range_update",
)
async def test_catalog_range_update(
    test_id: int,
    range_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    reference_range = service.repository.get_reference_range(range_id)
    if reference_range is None or reference_range.test_id != test_id:
        raise CatalogNotFoundError("reference range not found")
    form = await request.form()
    values = _form_values(form, RANGE_FORM_FIELDS)
    _parse_context_metadata(values)
    try:
        service.update_reference_range(
            test_id,
            range_id,
            ReferenceRangeUpdate.model_validate(values),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/range_form.html",
            {
                "page_title": "Test Catalog",
                "test": test,
                "mode": "edit",
                "values": values,
                "range": reference_range,
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{test_id}/reference-ranges/{range_id}/activation",
    response_class=HTMLResponse,
    name="test_catalog_range_activation",
)
async def test_catalog_range_activation(
    test_id: int,
    range_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    try:
        service.set_reference_range_activation(
            test_id,
            range_id,
            ActivationRequest(
                is_active=_checkbox(form, "is_active"),
                reason=_form_value(form, "reason") or "",
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request, "test_catalog/detail.html", _detail_context(service, test_id), exc
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/{test_id}/qualitative-options/new",
    response_class=HTMLResponse,
    name="test_catalog_option_new",
)
def test_catalog_option_new(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/option_form.html",
        context={
            "page_title": "Test Catalog",
            "test": test,
            "mode": "create",
            "values": {"sort_order": 0, "is_active": True},
            "errors": [],
            "option": None,
        },
    )


@router.post(
    "/{test_id}/qualitative-options/new",
    response_class=HTMLResponse,
    name="test_catalog_option_create",
)
async def test_catalog_option_create(
    test_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    form = await request.form()
    values = _form_values(form, OPTION_FORM_FIELDS)
    values["is_abnormal"] = _checkbox(form, "is_abnormal")
    try:
        service.create_qualitative_option(
            test_id, QualitativeOptionCreate.model_validate(values), actor_reference=actor.reference
        )
    except (
        ValidationError,
        CatalogNotFoundError,
        DuplicateCatalogCodeError,
        InvalidCatalogOperationError,
    ) as exc:
        return _render_form_error(
            request,
            "test_catalog/option_form.html",
            {
                "page_title": "Test Catalog",
                "test": test,
                "mode": "create",
                "values": values,
                "option": None,
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/{test_id}/qualitative-options/{option_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_option_edit",
)
def test_catalog_option_edit(
    test_id: int,
    option_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    option = service.repository.get_qualitative_option(option_id)
    if option is None or option.test_id != test_id:
        raise CatalogNotFoundError("qualitative option not found")
    return templates.TemplateResponse(
        request=request,
        name="test_catalog/option_form.html",
        context={
            "page_title": "Test Catalog",
            "test": test,
            "mode": "edit",
            "values": {
                field: getattr(option, field) for field in OPTION_FORM_FIELDS if field != "reason"
            },
            "errors": [],
            "option": option,
        },
    )


@router.post(
    "/{test_id}/qualitative-options/{option_id}/edit",
    response_class=HTMLResponse,
    name="test_catalog_option_update",
)
async def test_catalog_option_update(
    test_id: int,
    option_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    test = service.get_test(test_id)
    option = service.repository.get_qualitative_option(option_id)
    if option is None or option.test_id != test_id:
        raise CatalogNotFoundError("qualitative option not found")
    form = await request.form()
    values = _form_values(form, OPTION_FORM_FIELDS)
    values["is_abnormal"] = _checkbox(form, "is_abnormal")
    try:
        service.update_qualitative_option(
            test_id,
            option_id,
            QualitativeOptionUpdate.model_validate(values),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request,
            "test_catalog/option_form.html",
            {
                "page_title": "Test Catalog",
                "test": test,
                "mode": "edit",
                "values": values,
                "option": option,
            },
            exc,
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post(
    "/{test_id}/qualitative-options/{option_id}/activation",
    response_class=HTMLResponse,
    name="test_catalog_option_activation",
)
async def test_catalog_option_activation(
    test_id: int,
    option_id: int,
    request: Request,
    service: TestCatalogServiceDependency,
    actor: AdminActorDependency,
) -> Response:
    form = await request.form()
    try:
        service.set_qualitative_option_activation(
            test_id,
            option_id,
            ActivationRequest(
                is_active=_checkbox(form, "is_active"),
                reason=_form_value(form, "reason") or "",
            ),
            actor_reference=actor.reference,
        )
    except (ValidationError, CatalogNotFoundError, InvalidCatalogOperationError) as exc:
        return _render_form_error(
            request, "test_catalog/detail.html", _detail_context(service, test_id), exc
        )
    return RedirectResponse(
        request.url_for("test_catalog_detail", test_id=test_id),
        status_code=status.HTTP_303_SEE_OTHER,
    )
