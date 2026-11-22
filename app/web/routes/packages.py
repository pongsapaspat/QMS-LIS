from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import SessionDependency
from app.core.security import Actor, AdminActorDependency
from app.domain.exceptions import CatalogNotFoundError, DuplicateCatalogCodeError
from app.models.test_catalog import LabTest
from app.schemas.package import PackageCreate
from app.services.package import PackageService
from app.web.templates import templates

router = APIRouter(prefix="/packages")


def render_form(
    request: Request, session: Session, values: dict[str, Any],
    errors: list[str] | None = None, status: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="packages/form.html",
        context={
            "page_title": "Package",
            "values": values,
            "errors": errors or [],
            "tests": list(session.scalars(select(LabTest).order_by(LabTest.code))),
        },
        status_code=status,
    )


@router.get("", name="package_list")
def package_list(
    request: Request, session: SessionDependency, actor: AdminActorDependency
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="packages/list.html",
        context={
            "page_title": "Packages",
            "packages": PackageService(session).list(),
        },
    )


@router.get("/new", name="package_new")
def package_new(
    request: Request, session: SessionDependency, actor: AdminActorDependency
) -> HTMLResponse:
    return render_form(request, session, {"is_active": True, "test_ids": []})


@router.get("/{package_id}/edit", name="package_edit")
def package_edit(
    package_id: int, request: Request, session: SessionDependency, actor: AdminActorDependency
) -> HTMLResponse:
    p = PackageService(session).get(package_id)
    return render_form(
        request,
        session,
        {
            "code": p.code,
            "name": p.name,
            "price": p.price,
            "is_active": p.is_active,
            "test_ids": [str(t.id) for t in p.tests],
        },
    )


async def save_package_form(
    request: Request, session: Session, actor: Actor, package_id: int | None = None
) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        key: str(form.get(key, "")) for key in ("code", "name", "price", "reason")
    }
    values["test_ids"] = form.getlist("test_ids")
    values["is_active"] = form.get("is_active") == "on"
    try:
        PackageService(session).save(
            PackageCreate.model_validate(values), actor.reference, package_id
        )
    except (ValidationError, CatalogNotFoundError, DuplicateCatalogCodeError) as exc:
        errors = (
            [e["msg"] for e in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]
        )
        return render_form(request, session, values, errors, 422)
    return RedirectResponse("/packages?success=package-saved", status_code=303)


@router.post("/new")
async def package_create(
    request: Request, session: SessionDependency, actor: AdminActorDependency
) -> Response:
    return await save_package_form(request, session, actor)


@router.post("/{package_id}/edit")
async def package_update(
    package_id: int, request: Request, session: SessionDependency, actor: AdminActorDependency
) -> Response:
    return await save_package_form(request, session, actor, package_id)
