from datetime import date
from io import StringIO
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.sql.elements import ColumnElement

from app.api.dependencies import SessionDependency
from app.core.security import AuditReaderDependency
from app.core.time import app_date_range_utc, to_app_timezone
from app.models.audit import AuditLog
from app.web.templates import templates

router = APIRouter(prefix="/audit-logs")


def _conditions(
    date_from: date | None,
    date_to: date | None,
    actor: str | None,
    event_type: str | None,
    entity_type: str | None,
    entity_id: int | None,
) -> list[ColumnElement[bool]]:
    start, end = app_date_range_utc(date_from, date_to)
    conditions: list[ColumnElement[bool]] = []
    if start is not None:
        conditions.append(AuditLog.occurred_at >= start)
    if end is not None:
        conditions.append(AuditLog.occurred_at < end)
    if actor:
        conditions.append(AuditLog.actor_reference == actor.strip())
    if event_type:
        conditions.append(AuditLog.event_type == event_type.strip())
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type.strip())
    if entity_id is not None:
        conditions.append(AuditLog.entity_id == entity_id)
    return conditions


def _query_string(
    date_from: date | None,
    date_to: date | None,
    actor: str | None,
    event_type: str | None,
    entity_type: str | None,
    entity_id: int | None,
    page: int | None = None,
) -> str:
    values: dict[str, str | int] = {}
    if date_from:
        values["date_from"] = date_from.isoformat()
    if date_to:
        values["date_to"] = date_to.isoformat()
    if actor:
        values["actor"] = actor
    if event_type:
        values["event_type"] = event_type
    if entity_type:
        values["entity_type"] = entity_type
    if entity_id is not None:
        values["entity_id"] = entity_id
    if page is not None:
        values["page"] = page
    return urlencode(values)


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
    page: int = 1,
) -> HTMLResponse:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must not be after date_to",
        )

    page = max(page, 1)
    page_size = 50
    conditions = _conditions(date_from, date_to, actor, event_type, entity_type, entity_id)
    total = session.scalar(select(func.count(AuditLog.id)).where(*conditions)) or 0
    entries = list(
        session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
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
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_previous": page > 1,
            "has_next": page * page_size < total,
            "previous_query": _query_string(
                date_from, date_to, actor, event_type, entity_type, entity_id, page - 1
            ),
            "next_query": _query_string(
                date_from, date_to, actor, event_type, entity_type, entity_id, page + 1
            ),
            "export_query": _query_string(
                date_from, date_to, actor, event_type, entity_type, entity_id
            ),
        },
    )


@router.get("/export.csv")
def audit_log_export(
    session: SessionDependency,
    _: AuditReaderDependency,
    date_from: date | None = None,
    date_to: date | None = None,
    actor: str | None = None,
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
) -> StreamingResponse:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    conditions = _conditions(date_from, date_to, actor, event_type, entity_type, entity_id)
    entries = session.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(10000)
    )
    output = StringIO()
    output.write("id,occurred_at,actor_reference,event_type,entity_type,entity_id,changed_fields,reason\n")
    for entry in entries:
        values = [
            str(entry.id),
            to_app_timezone(entry.occurred_at).isoformat(),
            entry.actor_reference,
            entry.event_type,
            entry.entity_type,
            str(entry.entity_id),
            ";".join(entry.changed_fields),
            entry.reason,
        ]
        output.write(",".join('"' + value.replace('"', '""') + '"' for value in values) + "\n")
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=audit-logs.csv"},
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
