import time

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.passwords import hash_password
from app.domain.exceptions import (
    BranchNotFoundError,
    CatalogNotFoundError,
    DuplicateCatalogCodeError,
    DuplicatePatientIdentifierError,
    InvalidCatalogOperationError,
    InvalidPatientChangeError,
    InvalidResultOperationError,
    InvalidSpecimenOperationError,
    OrderNotFoundError,
    PatientNotFoundError,
    PossibleDuplicatePatientError,
    ResultNotFoundError,
    SpecimenNotFoundError,
)
from app.models.user import User
from app.web.router import web_router
from app.web.templates import templates

settings = get_settings()


def bootstrap_admin() -> None:
    if not settings.bootstrap_admin_username or not settings.bootstrap_admin_password:
        return
    with SessionLocal() as session:
        username = settings.bootstrap_admin_username.strip().lower()
        if session.scalar(select(User).where(User.username == username)) is None:
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="ADMIN",
                    display_name="System Administrator",
                )
            )
            session.commit()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
)
bootstrap_admin()


@app.middleware("http")
async def require_web_login(request: Request, call_next: RequestResponseEndpoint) -> Response:
    html_request = "text/html" in request.headers.get("accept", "")
    public_path = request.url.path in {"/login", "/docs", "/redoc", "/openapi.json"}
    static_path = request.url.path.startswith("/static/")
    user_id = request.session.get("user_id")
    if isinstance(user_id, int):
        now = time.time()
        last_activity = request.session.get("last_activity_at", now)
        if isinstance(last_activity, (int, float)) and now - last_activity > settings.session_idle_timeout_seconds:
            request.session.clear()
            if html_request and not public_path and not static_path:
                return RedirectResponse(url=str(request.url_for("login")), status_code=303)
        else:
            request.session["last_activity_at"] = now
    if html_request and not public_path and not static_path and not request.session.get("user_id"):
        return RedirectResponse(url=str(request.url_for("login")), status_code=303)
    return await call_next(request)


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_https_only,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(web_router)


@app.exception_handler(HTTPException)
async def web_http_exception_handler(request: Request, exc: HTTPException) -> Response:
    accepts_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == status.HTTP_403_FORBIDDEN and accepts_html:
        return templates.TemplateResponse(
            request=request,
            name="errors/forbidden.html",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def safe_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    safe_errors = [
        {"location": error["loc"], "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
    )


@app.exception_handler(PatientNotFoundError)
async def patient_not_found_handler(request: Request, exc: PatientNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(BranchNotFoundError)
async def branch_not_found_handler(request: Request, exc: BranchNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(DuplicatePatientIdentifierError)
async def duplicate_patient_identifier_handler(
    request: Request, exc: DuplicatePatientIdentifierError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(PossibleDuplicatePatientError)
async def possible_duplicate_patient_handler(
    request: Request, exc: PossibleDuplicatePatientError
) -> JSONResponse:
    candidates = [
        {
            "patient_id": candidate.patient_id,
            "hn": candidate.hn,
            "display_name": candidate.display_name,
            "match_reason": candidate.match_reason,
        }
        for candidate in exc.candidates
    ]
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc), "candidates": candidates},
    )


@app.exception_handler(InvalidPatientChangeError)
async def invalid_patient_change_handler(
    request: Request, exc: InvalidPatientChangeError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )


@app.exception_handler(CatalogNotFoundError)
async def catalog_not_found_handler(request: Request, exc: CatalogNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(DuplicateCatalogCodeError)
async def duplicate_catalog_code_handler(
    request: Request, exc: DuplicateCatalogCodeError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(InvalidCatalogOperationError)
async def invalid_catalog_operation_handler(
    request: Request, exc: InvalidCatalogOperationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )


@app.exception_handler(OrderNotFoundError)
async def order_not_found_handler(request: Request, exc: OrderNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(SpecimenNotFoundError)
async def specimen_not_found_handler(request: Request, exc: SpecimenNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(InvalidSpecimenOperationError)
async def invalid_specimen_operation_handler(
    request: Request, exc: InvalidSpecimenOperationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )


@app.exception_handler(ResultNotFoundError)
async def result_not_found_handler(request: Request, exc: ResultNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(InvalidResultOperationError)
async def invalid_result_handler(
    request: Request, exc: InvalidResultOperationError
) -> JSONResponse:
    code = (
        status.HTTP_409_CONFLICT
        if "concurrent" in str(exc)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return JSONResponse(status_code=code, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
def root_health_check() -> dict[str, str]:
    return {"status": "ok"}
