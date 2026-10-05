
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.domain.exceptions import (
    BranchNotFoundError,
    DuplicatePatientIdentifierError,
    PatientNotFoundError,
)
from app.web.router import web_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(web_router)


@app.exception_handler(PatientNotFoundError)
async def patient_not_found_handler(
    request: Request, exc: PatientNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(BranchNotFoundError)
async def branch_not_found_handler(
    request: Request, exc: BranchNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(DuplicatePatientIdentifierError)
async def duplicate_patient_identifier_handler(
    request: Request, exc: DuplicatePatientIdentifierError
) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
def root_health_check() -> dict[str, str]:
    return {"status": "ok"}
