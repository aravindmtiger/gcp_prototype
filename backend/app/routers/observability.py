"""Observability: OTLP trace ingestion and the queries behind the Observability studio.

``POST /v1/traces`` is the standard OTLP/HTTP path, so any OpenTelemetry exporter can send here.
It accepts ``application/x-protobuf`` and ``application/json``. Authentication is the same as the
rest of the API (a Google ID token, or the dev header), so exporters send an Authorization header.
"""

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from app.config import get_settings
from app.deps import DbSession, User
from app.errors import AppError
from app.services.telemetry import (
    MAX_BODY_BYTES,
    get_trace,
    list_traces,
    parse_otlp,
    store_spans,
    summary,
)

ingest_router = APIRouter(tags=["observability"])
router = APIRouter(prefix="/api/v1/observability", tags=["observability"])


@ingest_router.post("/v1/traces", status_code=status.HTTP_200_OK)
async def ingest_traces(request: Request, session: DbSession, user: User) -> Response:
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "OTLP request is too large")

    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in ("application/x-protobuf", "application/json"):
        raise AppError(415, "Send OTLP as application/x-protobuf or application/json")
    try:
        rows = parse_otlp(body, protobuf=content_type == "application/x-protobuf")
    except Exception as exc:  # malformed payload: the exporter gets a 400, nothing is stored
        raise AppError(400, "The OTLP payload could not be decoded") from exc

    await store_spans(session, user.email, rows)
    # An empty protobuf message is a valid ExportTraceServiceResponse (full success).
    if content_type == "application/x-protobuf":
        return Response(content=b"", media_type="application/x-protobuf")
    return Response(content=b"{}", media_type="application/json")


@router.get("/traces")
async def traces(
    session: DbSession, user: User, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict]:
    rows = await list_traces(session, user.email, user.is_admin, limit)
    return [{**row, "started_at": row["started_at"].isoformat()} for row in rows]


@router.get("/traces/{trace_id}")
async def trace_detail(trace_id: str, session: DbSession, user: User) -> dict:
    spans = await get_trace(session, user.email, user.is_admin, trace_id.lower())
    if not spans:
        raise AppError(404, "Trace not found")
    return {
        "trace_id": trace_id.lower(),
        "spans": [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id or None,
                "name": s.name,
                "service_name": s.service_name,
                "kind": s.kind,
                "status_code": s.status_code,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "duration_ms": s.duration_ms,
                "attributes": s.attributes,
            }
            for s in spans
        ],
    }


@router.get("/summary")
async def trace_summary(
    session: DbSession, user: User, hours: int = Query(default=24, ge=1, le=720)
) -> dict:
    return await summary(session, user.email, user.is_admin, hours)


@router.get("/exporters")
async def exporters(user: User) -> dict:
    settings = get_settings()
    return {
        "tracing_enabled": settings.otel_enabled,
        "exporter": settings.otel_exporter,
        "otlp_endpoint": settings.otel_otlp_endpoint or None,
        "ingest_path": "/v1/traces",
        "accepted_formats": ["application/x-protobuf", "application/json"],
        "cloud_trace_project": settings.gcp_project_id or None,
    }
