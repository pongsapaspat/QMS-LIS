from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.api.dependencies import SessionDependency
from app.core.passwords import hash_password, verify_password
from app.core.security import ActorDependency
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.user import User
from app.web.templates import templates

router = APIRouter()


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
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="auth/login.html",
            status_code=401,
            context={"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
        )
    user.last_login_at = utc_now()
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
    request.session["actor"] = user.username
    request.session["role"] = user.role
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
    request.session.clear()
    return RedirectResponse(request.url_for("login"), status_code=303)
