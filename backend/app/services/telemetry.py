"""OpenTelemetry (OTLP/HTTP) trace ingestion, and the summaries the Observability studio shows.

Accepts both wire formats the OTLP spec defines: protobuf and JSON. Spans are stored per owner.
Admins see every owner's spans.
"""

import base64
import json
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpanRecord

MAX_BODY_BYTES = 4 * 1024 * 1024
ERROR_CODES = {2, "2", "STATUS_CODE_ERROR"}
OK_CODES = {1, "1", "STATUS_CODE_OK"}
MODEL_KEYS = ("gen_ai.request.model", "gen_ai.response.model")
INPUT_TOKEN_KEY = "gen_ai.usage.input_tokens"
OUTPUT_TOKEN_KEY = "gen_ai.usage.output_tokens"


def _hex_id(value: Any, from_base64: bool) -> str:
    if not value:
        return ""
    if from_base64:  # protobuf-to-dict renders bytes as base64
        return base64.b64decode(value).hex()
    return str(value).lower()


def _attr_value(value: dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "arrayValue" in value:
        return [_attr_value(item) for item in value["arrayValue"].get("values", [])]
    return None


def _attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {item["key"]: _attr_value(item.get("value", {})) for item in items or []}


def _nanos(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value) / 1e9, tz=UTC)


def parse_otlp(body: bytes, protobuf: bool) -> list[dict[str, Any]]:
    """Flattens an ExportTraceServiceRequest into one row per span. Malformed spans are skipped."""
    if protobuf:
        message = trace_service_pb2.ExportTraceServiceRequest.FromString(body)
        data = MessageToDict(message)
    else:
        data = json.loads(body)
    from_base64 = protobuf

    rows: list[dict[str, Any]] = []
    for resource_span in data.get("resourceSpans", []):
        resource = _attributes(resource_span.get("resource", {}).get("attributes"))
        service = str(resource.get("service.name", ""))
        for scope_span in resource_span.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                trace_id = _hex_id(span.get("traceId"), from_base64)
                span_id = _hex_id(span.get("spanId"), from_base64)
                if len(trace_id) != 32 or len(span_id) != 16:
                    continue
                start = int(span.get("startTimeUnixNano", 0))
                end = int(span.get("endTimeUnixNano", start))
                code = (span.get("status") or {}).get("code")
                rows.append(
                    {
                        "trace_id": trace_id,
                        "span_id": span_id,
                        "parent_span_id": _hex_id(span.get("parentSpanId"), from_base64),
                        "name": str(span.get("name", ""))[:300],
                        "service_name": service[:200],
                        "kind": str(span.get("kind", ""))[:40],
                        "status_code": (
                            "error"
                            if code in ERROR_CODES
                            else "ok" if code in OK_CODES else "unset"
                        ),
                        "start_time": _nanos(start),
                        "end_time": _nanos(end),
                        "duration_ms": max(end - start, 0) / 1e6,
                        "attributes": _attributes(span.get("attributes")),
                    }
                )
    return rows


async def store_spans(session: AsyncSession, owner_email: str, rows: list[dict[str, Any]]) -> int:
    """Stores spans not seen before. Exporters retry, so the same span can arrive twice."""
    if not rows:
        return 0
    trace_ids = {row["trace_id"] for row in rows}
    seen = set(
        (
            await session.execute(
                select(SpanRecord.trace_id, SpanRecord.span_id).where(
                    SpanRecord.trace_id.in_(trace_ids)
                )
            )
        ).all()
    )
    fresh = [row for row in rows if (row["trace_id"], row["span_id"]) not in seen]
    for row in fresh:
        session.add(SpanRecord(owner_email=owner_email, **row))
    await session.commit()
    return len(fresh)


def _scoped(statement, owner_email: str, is_admin: bool):
    return statement if is_admin else statement.where(SpanRecord.owner_email == owner_email)


async def list_traces(
    session: AsyncSession, owner_email: str, is_admin: bool, limit: int
) -> list[dict[str, Any]]:
    statement = (
        _scoped(select(SpanRecord), owner_email, is_admin)
        .order_by(SpanRecord.start_time.desc())
        .limit(5000)
    )
    spans = (await session.execute(statement)).scalars().all()
    by_trace: dict[str, list[SpanRecord]] = {}
    for span in spans:
        by_trace.setdefault(span.trace_id, []).append(span)

    summaries = []
    for trace_id, members in by_trace.items():
        root = next(
            (s for s in members if not s.parent_span_id), min(members, key=lambda s: s.start_time)
        )
        start = min(s.start_time for s in members)
        end = max(s.end_time for s in members)
        summaries.append(
            {
                "trace_id": trace_id,
                "root_name": root.name,
                "service_name": root.service_name,
                "started_at": start,
                "duration_ms": (end - start).total_seconds() * 1000,
                "span_count": len(members),
                "has_error": any(s.status_code == "error" for s in members),
            }
        )
    summaries.sort(key=lambda t: t["started_at"], reverse=True)
    return summaries[:limit]


async def get_trace(
    session: AsyncSession, owner_email: str, is_admin: bool, trace_id: str
) -> list[SpanRecord]:
    statement = _scoped(
        select(SpanRecord).where(SpanRecord.trace_id == trace_id), owner_email, is_admin
    )
    return list((await session.execute(statement.order_by(SpanRecord.start_time))).scalars().all())


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    rank = min(len(sorted_values), max(1, math.ceil(p / 100 * len(sorted_values))))
    return sorted_values[rank - 1]


async def summary(
    session: AsyncSession, owner_email: str, is_admin: bool, hours: int
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    statement = _scoped(
        select(SpanRecord).where(SpanRecord.start_time >= since), owner_email, is_admin
    )
    spans = (await session.execute(statement)).scalars().all()

    roots = [s for s in spans if not s.parent_span_id]
    durations = sorted(s.duration_ms for s in roots)
    models: Counter[str] = Counter()
    input_tokens = output_tokens = 0
    for span in spans:
        model = next((span.attributes[k] for k in MODEL_KEYS if span.attributes.get(k)), None)
        if model:
            models[str(model)] += 1
        input_tokens += int(span.attributes.get(INPUT_TOKEN_KEY) or 0)
        output_tokens += int(span.attributes.get(OUTPUT_TOKEN_KEY) or 0)

    errors = sum(1 for s in spans if s.status_code == "error")
    return {
        "hours": hours,
        "traces": len({s.trace_id for s in spans}),
        "spans": len(spans),
        "error_rate": errors / len(spans) if spans else 0.0,
        "p50_ms": _percentile(durations, 50),
        "p95_ms": _percentile(durations, 95),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "by_service": dict(Counter(s.service_name or "(unnamed)" for s in spans).most_common()),
        "by_model": [{"model": m, "spans": c} for m, c in models.most_common()],
    }
