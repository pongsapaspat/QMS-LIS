from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.api.dependencies import SessionDependency
from app.core.passwords import hash_password
from app.core.security import AdminOnlyActorDependency
from app.models.audit import AuditLog
from app.models.user import User
from app.web.templates import templates

router = APIRouter(prefix="/users")
ROLES = ("ADMIN", "IT", "LAB_TECH", "LAB_SUPERVISOR", "RECEPTION")


@router.get("", response_class=HTMLResponse, name="users")
def user_list(
    request: Request, session: SessionDependency, _: AdminOnlyActorDependency
) -> HTMLResponse:
    users = list(session.scalars(select(User).order_by(User.username)))
    return templates.TemplateResponse(
        request=request, name="users/list.html", context={"users": users}
    )


@router.post("", response_class=HTMLResponse, response_model=None, name="user_create")
async def user_create(
    request: Request, session: SessionDependency, actor: AdminOnlyActorDependency
) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    username = str(form.get("username", "")).strip().lower()
    password = str(form.get("password", ""))
    display_name = str(form.get("display_name", "")).strip()
    role = str(form.get("role", "")).strip().upper()
    error = None
    if not username or not password or not display_name or role not in ROLES:
        error = "กรุณากรอกข้อมูลให้ครบถ้วนและเลือก role ที่ถูกต้อง"
    elif session.scalar(select(User).where(User.username == username)) is not None:
        error = "ชื่อผู้ใช้นี้มีอยู่แล้ว"
    if error:
        users = list(session.scalars(select(User).order_by(User.username)))
        return templates.TemplateResponse(
            request=request, name="users/list.html", status_code=400,
            context={"users": users, "error": error, "roles": ROLES},
        )
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=display_name,
    )
    session.add(user)
    session.flush()
    session.add(AuditLog(event_type="USER_CREATED", entity_type="user", entity_id=user.id,
                         changed_fields=["username", "display_name", "role", "password"],
                         reason="User account created", actor_reference=actor.reference))
    session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/toggle", name="user_toggle")
def user_toggle(
    user_id: int, request: Request, session: SessionDependency, actor: AdminOnlyActorDependency
) -> RedirectResponse:
    user = session.get(User, user_id)
    if user is not None and user.username != actor.reference:
        user.is_active = not user.is_active
        session.add(
            AuditLog(
                event_type="USER_STATUS_CHANGED",
                entity_type="user",
                entity_id=user.id,
                changed_fields=["is_active"],
                reason="User active status changed",
                actor_reference=actor.reference,
            )
        )
        session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/unlock", name="user_unlock")
def user_unlock(
    user_id: int, request: Request, session: SessionDependency, actor: AdminOnlyActorDependency
) -> RedirectResponse:
    user = session.get(User, user_id)
    if user is not None and user.locked_until is not None:
        user.locked_until = None
        user.failed_login_count = 0
        user.failed_login_window_started_at = None
        session.add(
            AuditLog(
                event_type="USER_ACCOUNT_UNLOCKED",
                entity_type="user",
                entity_id=user.id,
                changed_fields=["locked_until", "failed_login_count"],
                reason="Account unlocked by administrator",
                actor_reference=actor.reference,
            )
        )
        session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/reset-password", name="user_reset_password")
async def user_reset_password(
    user_id: int, request: Request, session: SessionDependency, actor: AdminOnlyActorDependency
) -> RedirectResponse:
    form = await request.form()
    password = str(form.get("password", ""))
    user = session.get(User, user_id)
    if user is not None and password:
        user.password_hash = hash_password(password)
        session.add(
            AuditLog(
                event_type="USER_PASSWORD_RESET",
                entity_type="user",
                entity_id=user.id,
                changed_fields=["password"],
                reason="Password reset by administrator",
                actor_reference=actor.reference,
            )
        )
        session.commit()
    return RedirectResponse("/users", status_code=303)
