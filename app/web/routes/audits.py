from datetime import date

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.api.dependencies import SessionDependency
from app.core.security import AuditReaderDependency
from app.core.time import app_date_range_utc
from app.models.audit import AuditLog
from app.web.templates import templates

router = APIRouter(prefix="/audit-logs")


@router.get("", response_class=HTMLResponse)
def audit_log_list(
    request: Request,
    session: SessionDependency,
    _: AuditReaderDependency,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: str | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> HTMLResponse:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )

    start, end = app_date_range_utc(date_from, date_to)
    statement = select(AuditLog)
    if start is not None:
        statement = statement.where(AuditLog.occurred_at >= start)
    if end is not None:
        statement = statement.where(AuditLog.occurred_at < end)
    if actor:
        statement = statement.where(AuditLog.actor_reference == actor.strip())
    if event_type:
        statement = statement.where(AuditLog.event_type == event_type.strip())
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type.strip())
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)

    entries = list(
        session.scalars(
            statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(500)
        )
    )
    actors = list(
        session.scalars(
            select(AuditLog.actor_reference).distinct().order_by(AuditLog.actor_reference)
        )
    )
    event_types = list(
        session.scalars(select(AuditLog.event_type).distinct().order_by(AuditLog.event_type))
    )
    entity_types = list(
        session.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type))
    )
    return templates.TemplateResponse(
        request=request,
        name="audits/list.html",
        context={
            "entries": entries,
            "actors": actors,
            "event_types": event_types,
            "entity_types": entity_types,
            "filters": {
                "date_from": date_from,
                "date_to": date_to,
                "actor": actor or "",
                "event_type": event_type or "",
                "entity_type": entity_type or "",
                "entity_id": entity_id if entity_id is not None else "",
            },
        },
    )


@router.get("/{audit_id}", response_class=HTMLResponse)
def audit_log_detail(
    audit_id: int,
    request: Request,
    session: SessionDependency,
    _: AuditReaderDependency,
) -> HTMLResponse:
    entry = session.get(AuditLog, audit_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return templates.TemplateResponse(
        request=request,
        name="audits/detail.html",
        context={"entry": entry},
    )
