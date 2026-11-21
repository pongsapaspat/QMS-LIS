from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse, Response
from starlette.datastructures import UploadFile

from app.api.dependencies import SessionDependency
from app.core.security import (
    OUTLAB_DOCUMENT_ROLES,
    ActorDependency,
    OutlabDocumentManagerDependency,
    ResultReaderDependency,
    require_outlab_document_manager,
    require_result_mutator,
)
from app.domain.exceptions import InvalidResultOperationError
from app.models.audit import AuditLog
from app.models.outlab import OutlabDocument
from app.repositories.audit import AuditRepository
from app.services.outlab import MAX_DOCUMENT_BYTES, OutlabService
from app.web.templates import templates

router = APIRouter(prefix="/outlab")


@router.get("", name="outlab_queue")
def queue(
    request: Request,
    session: SessionDependency,
    actor: ResultReaderDependency,
    status: str = "",
    search: str = Query(default="", max_length=100),
    page: Annotated[int, Query(ge=1)] = 1,
):
    cases = OutlabService(session).queue(status, search, page)
    return templates.TemplateResponse(
        request=request,
        name="outlab/queue.html",
        context={
            "cases": cases[:25],
            "has_next": len(cases) > 25,
            "page": page,
            "status": status,
            "search": search,
            "page_title": "Outlab | ส่งตรวจภายนอก",
        },
    )


def render_detail(request, service, case_id, role, errors=None, values=None, status_code=200):
    case = service.get(case_id)
    return templates.TemplateResponse(
        request=request,
        name="outlab/detail.html",
        status_code=status_code,
        context={
            "case": case,
            "specimen": service.specimen(case),
            "page_title": "Outlab",
            "can_send": role in {"ADMIN", "IT", "LAB_TECH"},
            "can_manage_documents": role in OUTLAB_DOCUMENT_ROLES,
            "history": AuditRepository(service.session).list_for_entity("outlab_case", case_id),
            "errors": errors or [],
            "values": values or {},
        },
    )


@router.get("/{case_id:int}", name="outlab_detail")
def detail(
    case_id: int, request: Request, session: SessionDependency, actor: ResultReaderDependency
):
    return render_detail(request, OutlabService(session), case_id, actor.role)


@router.post("/{case_id:int}/{action}", name="outlab_action")
async def action(
    case_id: int,
    action: str,
    request: Request,
    session: SessionDependency,
    actor: ActorDependency,
):
    # Check the responsibility before parsing uploads or changing referral state.
    if action == "send":
        require_result_mutator(actor)
    elif action == "receive":
        require_outlab_document_manager(actor)
    else:
        raise InvalidResultOperationError("Unknown Outlab action")
    service = OutlabService(session)
    form = await request.form()
    values = {key: str(form.get(key, "")) for key in ("lab_name", "external_reference", "notes")}
    try:
        if action == "send":
            service.send(
                case_id,
                values["lab_name"],
                values["external_reference"],
                values["notes"],
                actor.reference,
            )
        elif action == "receive":
            document = form.get("document")
            if not isinstance(document, UploadFile):
                raise InvalidResultOperationError("Attach the original laboratory report")
            content = await document.read(MAX_DOCUMENT_BYTES + 1)
            await document.close()
            service.receive(
                case_id,
                document.filename or "report",
                content,
                values["external_reference"],
                actor.reference,
            )
        else:
            raise InvalidResultOperationError("Unknown Outlab action")
    except (InvalidResultOperationError, ValueError) as exc:
        session.rollback()
        return render_detail(request, service, case_id, actor.role, [str(exc)], values, 422)
    return RedirectResponse(request.url_for("outlab_detail", case_id=case_id), status_code=303)


@router.post("/{case_id:int}/document/check", name="outlab_check")
async def check(
    case_id: int,
    request: Request,
    session: SessionDependency,
    actor: OutlabDocumentManagerDependency,
):
    form = await request.form()
    service = OutlabService(session)
    try:
        if form.get("decision") == "reject":
            service.reject_document(case_id, str(form.get("reason", "")), actor.reference)
        else:
            service.check(case_id, actor.reference, form.get("confirmed") == "on")
    except InvalidResultOperationError as exc:
        session.rollback()
        return render_detail(request, service, case_id, actor.role, [str(exc)], status_code=422)
    return RedirectResponse(request.url_for("outlab_detail", case_id=case_id), status_code=303)


@router.get("/documents/{document_id:int}", name="outlab_document")
def document(document_id: int, session: SessionDependency, actor: ResultReaderDependency):
    document = session.get(OutlabDocument, document_id)
    if document is None:
        raise InvalidResultOperationError("Outlab document not found")
    content, filename, content_type = document.content, document.filename, document.content_type
    session.add(
        AuditLog(
            event_type="OUTLAB_DOCUMENT_DOWNLOADED",
            entity_type="outlab_case",
            entity_id=document.case_id,
            changed_fields=[],
            reason="original document download",
            actor_reference=actor.reference,
        )
    )
    session.commit()
    return Response(
        content,
        media_type=content_type,
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
