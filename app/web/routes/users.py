from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.api.dependencies import SessionDependency
from app.core.passwords import hash_password
from app.core.security import AdminOnlyActorDependency
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.professional import ProfessionalProfile
from app.web.templates import templates

router = APIRouter(prefix="/users")
ROLES = ("ADMIN", "IT", "LAB_TECH", "LAB_SUPERVISOR", "RECEPTION")


@router.get("", response_class=HTMLResponse, name="users")
def user_list(
    request: Request, session: SessionDependency, _: AdminOnlyActorDependency
) -> HTMLResponse:
    users = list(session.scalars(select(User).order_by(User.username)))
    return templates.TemplateResponse(
        request=request, name="users/list.html", context={"users": users, "roles": ROLES}
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
    try:
        profile = ProfessionalProfile.model_validate(
            {
                "full_name": form.get("full_name"),
                "professional_license_number": form.get("professional_license_number"),
            }
        )
    except ValidationError:
        profile = ProfessionalProfile()
        error = "ชื่อ-นามสกุลต้องไม่เกิน 200 ตัวอักษร และเลข ทน. ต้องไม่เกิน 100 ตัวอักษร"
    if not username or not password or not display_name or role not in ROLES:
        error = "กรุณากรอกข้อมูลให้ครบถ้วนและเลือก role ที่ถูกต้อง"
    elif session.scalar(select(User).where(User.username == username)) is not None:
        error = "ชื่อผู้ใช้นี้มีอยู่แล้ว"
    elif role in {"LAB_TECH", "LAB_SUPERVISOR"} and (
        not profile.full_name or not profile.professional_license_number
    ):
        error = "กรุณากรอกชื่อ-นามสกุลและเลข ทน. สำหรับผู้ลงผลและผู้อนุมัติผล"
    if error:
        users = list(session.scalars(select(User).order_by(User.username)))
        return templates.TemplateResponse(
            request=request,
            name="users/list.html",
            status_code=400,
            context={"users": users, "error": error, "roles": ROLES},
        )
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=display_name,
        full_name=profile.full_name,
        professional_license_number=profile.professional_license_number,
    )
    session.add(user)
    session.flush()
    session.add(
        AuditLog(
            event_type="USER_CREATED",
            entity_type="user",
            entity_id=user.id,
            changed_fields=[
                "username",
                "display_name",
                "role",
                "password",
                "full_name",
                "professional_license_number",
            ],
            reason="User account created",
            actor_reference=actor.reference,
        )
    )
    session.commit()
    return RedirectResponse("/users", status_code=303)


@router.post("/{user_id}/profile", response_model=None, name="user_professional_profile")
async def user_professional_profile(
    user_id: int, request: Request, session: SessionDependency, actor: AdminOnlyActorDependency
) -> HTMLResponse | RedirectResponse:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    form = await request.form()
    try:
        profile = ProfessionalProfile.model_validate(
            {
                "full_name": form.get("full_name"),
                "professional_license_number": form.get("professional_license_number"),
            }
        )
        if user.role in {"LAB_TECH", "LAB_SUPERVISOR"} and (
            not profile.full_name or not profile.professional_license_number
        ):
            raise ValueError("กรุณากรอกชื่อ-นามสกุลและเลข ทน. ให้ครบ")
    except (ValidationError, ValueError) as exc:
        error = "ชื่อ-นามสกุลหรือเลข ทน. ยาวเกินกำหนด" if isinstance(exc, ValidationError) else str(exc)
        return templates.TemplateResponse(
            request=request,
            name="users/list.html",
            status_code=422,
            context={
                "users": list(session.scalars(select(User).order_by(User.username))),
                "roles": ROLES,
                "error": error,
            },
        )
    changed = [
        field for field, value in profile.model_dump().items() if getattr(user, field) != value
    ]
    if changed:
        for field, value in profile.model_dump().items():
            setattr(user, field, value)
        session.add(
            AuditLog(
                event_type="USER_PROFESSIONAL_PROFILE_UPDATED",
                entity_type="user",
                entity_id=user.id,
                changed_fields=changed,
                reason="Updated report identity",
                actor_reference=actor.reference,
            )
        )
        session.commit()
    return RedirectResponse("/users?success=profile-updated", status_code=303)


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
