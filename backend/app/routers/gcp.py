"""Google Cloud resources that the platform forms offer as choices."""

from fastapi import APIRouter

from app.config import get_settings
from app.deps import User
from app.errors import AppError
from app.services.gcp_catalog import (
    CatalogError,
    list_bigquery_tables,
    list_cloud_traces,
    list_mcp_endpoints,
    list_rag_corpora,
)

router = APIRouter(prefix="/api/v1/gcp", tags=["gcp"])


def _wrap(error: CatalogError) -> AppError:
    return AppError(error.status_code, str(error))


@router.get("/status")
async def status(user: User) -> dict:
    settings = get_settings()
    return {
        "project": settings.gcp_project_id or None,
        "location": settings.gcp_location,
        "configured": bool(settings.gcp_project_id),
    }


@router.get("/mcp-endpoints")
async def mcp_endpoints(user: User) -> list[dict]:
    try:
        return await list_mcp_endpoints(get_settings())
    except CatalogError as exc:
        raise _wrap(exc) from exc


@router.get("/rag-corpora")
async def rag_corpora(user: User) -> list[dict]:
    try:
        return await list_rag_corpora(get_settings())
    except CatalogError as exc:
        raise _wrap(exc) from exc


@router.get("/bigquery-tables")
async def bigquery_tables(user: User) -> list[dict]:
    try:
        return await list_bigquery_tables(get_settings())
    except CatalogError as exc:
        raise _wrap(exc) from exc


@router.get("/cloud-traces")
async def cloud_traces(user: User, limit: int = 50) -> list[dict]:
    try:
        return await list_cloud_traces(get_settings(), limit)
    except CatalogError as exc:
        raise _wrap(exc) from exc
