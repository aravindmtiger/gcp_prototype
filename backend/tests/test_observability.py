"""OTLP ingestion and trace queries. Local only: no spans leave the process."""

import json
import time

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.resource.v1 import resource_pb2
from opentelemetry.proto.trace.v1 import trace_pb2

from app.db import SessionLocal
from app.main import app
from app.services.seed import ensure_default_guardrail

ALICE = {"X-Dev-User": "alice@example.com"}
TRACE_ID = bytes.fromhex("0af7651916cd43dd8448eb211c80319c")


@pytest.fixture
async def client(database):
    async with SessionLocal() as session:
        await ensure_default_guardrail(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _request_proto(model: str | None = None) -> bytes:
    now = time.time_ns() - 60_000_000_000  # a minute ago, inside the summary window
    root = trace_pb2.Span(
        trace_id=TRACE_ID,
        span_id=bytes.fromhex("b7ad6b7169203331"),
        name="agent.run",
        start_time_unix_nano=now,
        end_time_unix_nano=now + 500_000_000,
        status=trace_pb2.Status(code=trace_pb2.Status.STATUS_CODE_OK),
    )
    child = trace_pb2.Span(
        trace_id=TRACE_ID,
        span_id=bytes.fromhex("00f067aa0ba902b7"),
        parent_span_id=bytes.fromhex("b7ad6b7169203331"),
        name="model.call",
        start_time_unix_nano=now + 100_000_000,
        end_time_unix_nano=now + 400_000_000,
        status=trace_pb2.Status(code=trace_pb2.Status.STATUS_CODE_ERROR),
        attributes=[
            common_pb2.KeyValue(
                key="gen_ai.request.model",
                value=common_pb2.AnyValue(string_value=model or "gemini-2.5-flash"),
            ),
            common_pb2.KeyValue(
                key="gen_ai.usage.input_tokens", value=common_pb2.AnyValue(int_value=120)
            ),
        ],
    )
    request = trace_service_pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                resource=resource_pb2.Resource(
                    attributes=[
                        common_pb2.KeyValue(
                            key="service.name",
                            value=common_pb2.AnyValue(string_value="support-agent"),
                        )
                    ]
                ),
                scope_spans=[trace_pb2.ScopeSpans(spans=[root, child])],
            )
        ]
    )
    return request.SerializeToString()


async def test_protobuf_spans_are_stored_and_queryable(client):
    response = await client.post(
        "/v1/traces",
        headers={**ALICE, "Content-Type": "application/x-protobuf"},
        content=_request_proto(),
    )
    assert response.status_code == 200, response.text

    listed = (await client.get("/api/v1/observability/traces", headers=ALICE)).json()
    assert len(listed) == 1
    assert listed[0]["trace_id"] == TRACE_ID.hex()
    assert listed[0]["root_name"] == "agent.run"
    assert listed[0]["service_name"] == "support-agent"
    assert listed[0]["has_error"] is True
    assert listed[0]["duration_ms"] == pytest.approx(500.0)

    detail = (
        await client.get(f"/api/v1/observability/traces/{TRACE_ID.hex()}", headers=ALICE)
    ).json()
    names = [s["name"] for s in detail["spans"]]
    assert names == ["agent.run", "model.call"]
    assert detail["spans"][1]["parent_span_id"] == "b7ad6b7169203331"


async def test_json_spans_and_retries_are_not_duplicated(client):
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "json-svc"}}]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11" * 16,
                                "spanId": "22" * 8,
                                "name": "json.root",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }
    body = json.dumps(payload).encode()
    headers = {**ALICE, "Content-Type": "application/json"}
    assert (await client.post("/v1/traces", headers=headers, content=body)).status_code == 200
    assert (await client.post("/v1/traces", headers=headers, content=body)).status_code == 200

    detail = (await client.get(f"/api/v1/observability/traces/{'11' * 16}", headers=ALICE)).json()
    assert len(detail["spans"]) == 1
    assert detail["spans"][0]["duration_ms"] == pytest.approx(1000.0)


async def test_summary_counts_models_and_tokens(client):
    await client.post(
        "/v1/traces",
        headers={**ALICE, "Content-Type": "application/x-protobuf"},
        content=_request_proto(),
    )
    summary = (await client.get("/api/v1/observability/summary", headers=ALICE)).json()
    assert summary["traces"] == 1
    assert summary["spans"] == 2
    assert summary["error_rate"] == pytest.approx(0.5)
    assert summary["input_tokens"] == 120
    assert summary["by_model"] == [{"model": "gemini-2.5-flash", "spans": 1}]


async def test_other_users_cannot_read_a_trace(client):
    await client.post(
        "/v1/traces",
        headers={**ALICE, "Content-Type": "application/x-protobuf"},
        content=_request_proto(),
    )
    other = await client.get(
        f"/api/v1/observability/traces/{TRACE_ID.hex()}",
        headers={"X-Dev-User": "carol@example.com"},
    )
    assert other.status_code == 404


async def test_unsupported_content_type_is_rejected(client):
    response = await client.post(
        "/v1/traces", headers={**ALICE, "Content-Type": "text/plain"}, content=b"x"
    )
    assert response.status_code == 415
