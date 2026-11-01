from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.api.dependencies import SessionDependency
from app.core.passwords import verify_password
from app.models.audit import AuditLog
from app.models.base import utc_now
from app.models.user import User
from app.web.templates import templates

router = APIRouter()


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
