from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.core.database import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health", summary="API health check")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Application readiness check")
def readiness_check() -> dict[str, str]:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return {"status": "ready", "database": "ok"}
