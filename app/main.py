
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.domain.exceptions import (
    BranchNotFoundError,
    CatalogNotFoundError,
    DuplicateCatalogCodeError,
    DuplicatePatientIdentifierError,
    InvalidCatalogOperationError,
    InvalidPatientChangeError,
    PatientNotFoundError,
    PossibleDuplicatePatientError,
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
async def catalog_not_found_handler(
    request: Request, exc: CatalogNotFoundError
) -> JSONResponse:
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


@app.get("/health", tags=["health"])
def root_health_check() -> dict[str, str]:
    return {"status": "ok"}
