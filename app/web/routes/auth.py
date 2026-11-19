from datetime import timedelta
from secrets import token_urlsafe

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, func, select, text

from app.api.dependencies import SessionDependency
from app.core.config import get_settings
from app.core.passwords import hash_password, verify_password
from app.core.security import ActorDependency
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.user import User
from app.models.login_session import LoginSession
from app.web.templates import templates

router = APIRouter()
settings = get_settings()


def _session_user(request: Request, session: SessionDependency) -> User:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


@router.get("/login", response_class=HTMLResponse, name="login")
def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request, name="auth/login.html", context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse, response_model=None, name="login_submit")
async def login(request: Request, session: SessionDependency) -> HTMLResponse | RedirectResponse:
    form = await request.form()
    username = str(form.get("username", "")).strip().lower()
    password = str(form.get("password", ""))
    user = session.scalar(select(User).where(User.username == username))
    now = utc_now()
    is_locked = user is not None and user.locked_until is not None and user.locked_until > now
    if user is not None and user.locked_until is not None and user.locked_until <= now:
        user.locked_until = None
        user.failed_login_count = 0
        user.failed_login_window_started_at = None
    invalid_login = (
        user is None
        or not user.is_active
        or is_locked
        or not verify_password(password, user.password_hash)
    )
    if invalid_login:
        if user is None:
            reason = "Login failed: unknown username"
            entity_id = 0
        elif not user.is_active:
            reason = "Login failed: inactive account"
            entity_id = user.id
        elif is_locked:
            reason = "Login failed: account locked"
            entity_id = user.id
        else:
            reason = "Login failed: invalid password"
            entity_id = user.id
        session.add(
            AuditLog(
                event_type="USER_LOGIN_FAILED",
                entity_type="user_login",
                entity_id=entity_id,
                changed_fields=[],
                reason=reason,
                actor_reference=username or "unknown",
            )
        )
        if user is not None and user.is_active and not is_locked:
            window_start = user.failed_login_window_started_at
            if (
                window_start is None
                or now - window_start > timedelta(seconds=settings.login_failure_window_seconds)
            ):
                user.failed_login_count = 1
                user.failed_login_window_started_at = now
                
            else:
                user.failed_login_count += 1
            if user.failed_login_count >= settings.login_failure_limit:
                user.locked_until = now + timedelta(seconds=settings.account_lockout_seconds)
                session.add(
                    AuditLog(
                        event_type="USER_ACCOUNT_LOCKED",
                        entity_type="user",
                        entity_id=user.id,
                        changed_fields=["locked_until", "failed_login_count"],
                        reason="Account locked after repeated failed logins",
                        actor_reference=user.username,
                    )
                )
        session.commit()
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            status_code=401,
            context={"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
        )
    assert user is not None and user.is_active and not is_locked
    # Serialize admissions across processes on PostgreSQL.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7142026)"))
    session.execute(delete(LoginSession).where(LoginSession.expires_at <= now))
    old_token = request.session.get("login_token")
    if isinstance(old_token, str):
        session.execute(delete(LoginSession).where(LoginSession.token == old_token))
    if (session.scalar(select(func.count()).select_from(LoginSession)) or 0) >= settings.max_active_sessions:
        session.rollback()
        return templates.TemplateResponse(
            request=request, name="auth/login.html", status_code=409,
            context={"error": "ระบบมีผู้ใช้งานครบจำนวนแล้ว กรุณาลองใหม่ภายหลัง"},
        )
    login_token = token_urlsafe(32)
    maximum = now + timedelta(seconds=settings.session_max_age_seconds)
    session.add(LoginSession(
        token=login_token, user_id=user.id,
        expires_at=min(maximum, now + timedelta(seconds=settings.session_idle_timeout_seconds)),
        maximum_expires_at=maximum,
    ))
    user.last_login_at = utc_now()
    user.failed_login_count = 0
    user.failed_login_window_started_at = None
    user.locked_until = None
    session.add(
        AuditLog(
            event_type="USER_LOGGED_IN",
            entity_type="user",
            entity_id=user.id,
            changed_fields=["last_login_at"],
            reason="User logged in",
            actor_reference=user.username,
        )
    )
    session.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["login_token"] = login_token
    request.session["actor"] = user.username
    request.session["role"] = user.role
    request.session["last_activity_at"] = utc_now().timestamp()
    return RedirectResponse(request.url_for("home"), status_code=303)


@router.get("/change-password", response_class=HTMLResponse, name="change_password")
def change_password_form(
    request: Request, session: SessionDependency, _: ActorDependency
) -> HTMLResponse:
    _session_user(request, session)
    return templates.TemplateResponse(
        request=request, name="auth/change_password.html", context={"error": None, "success": None}
    )


@router.post(
    "/change-password",
    response_class=HTMLResponse,
    response_model=None,
    name="change_password_submit",
)
async def change_password(
    request: Request, session: SessionDependency, _: ActorDependency
) -> HTMLResponse | RedirectResponse:
    user = _session_user(request, session)
    form = await request.form()
    current_password = str(form.get("current_password", ""))
    new_password = str(form.get("new_password", ""))
    confirm_password = str(form.get("confirm_password", ""))
    error: str | None = None
    if not verify_password(current_password, user.password_hash):
        error = "รหัสผ่านเดิมไม่ถูกต้อง"
    elif len(new_password) < 8:
        error = "รหัสผ่านใหม่ต้องมีอย่างน้อย 8 ตัวอักษร"
    elif new_password != confirm_password:
        error = "รหัสผ่านใหม่และการยืนยันไม่ตรงกัน"
    elif verify_password(new_password, user.password_hash):
        error = "รหัสผ่านใหม่ต้องไม่ซ้ำกับรหัสผ่านเดิม"
    if error:
        return templates.TemplateResponse(
            request=request,
            name="auth/change_password.html",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            context={"error": error, "success": None},
        )
    user.password_hash = hash_password(new_password)
    session.add(
        AuditLog(
            event_type="USER_PASSWORD_CHANGED",
            entity_type="user",
            entity_id=user.id,
            changed_fields=["password"],
            reason="User changed own password",
            actor_reference=user.username,
        )
    )
    session.commit()
    return templates.TemplateResponse(
        request=request,
        name="auth/change_password.html",
        context={"error": None, "success": "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว"},
    )


@router.post("/logout", name="logout")
def logout(request: Request, session: SessionDependency) -> RedirectResponse:
    session.execute(delete(LoginSession).where(
        LoginSession.token == request.session.get("login_token", "")
    ))
    user_id = request.session.get("user_id")
    actor = request.session.get("actor")
    if isinstance(user_id, int) and isinstance(actor, str):
        session.add(
            AuditLog(
                event_type="USER_LOGGED_OUT",
                entity_type="user",
                entity_id=user_id,
                changed_fields=[],
                reason="User logged out",
                actor_reference=actor,
            )
        )
        session.commit()
    session.commit()
    request.session.clear()
    return RedirectResponse(request.url_for("login"), status_code=303)
