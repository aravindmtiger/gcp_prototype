"""Liveness and readiness probes used by Cloud Run and local tooling."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.db import check_db
from app.errors import log_error

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def liveness() -> dict[str, str]:
    """Process is up. Does not touch dependencies, so a DB outage does not restart the container."""
    return {"status": "ok"}


@router.get("/readyz")
async def readiness() -> JSONResponse:
    try:
        await check_db()
    except Exception as exc:
        log_error(exc, context={"check": "database"})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"status": "degraded"}
        )
    return JSONResponse(content={"status": "ready"})
