"""Integration tests against PostgreSQL + pgvector.

Skipped unless TEST_DATABASE_URL is set, e.g.
  TEST_DATABASE_URL=postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow pytest
"""

import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (PostgreSQL)"
)

ALICE = {"X-Dev-User": "alice@example.com"}
POLICY = "Refunds are issued within 14 days of purchase when the receipt is attached."

RAG_FLOW = {
    "name": "Policy assistant",
    "definition": {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "question"},
            {
                "id": "kb",
                "type": "retriever",
                "input_var": "question",
                "output_var": "context",
                "config": {"collection": "policies", "top_k": 1},
            },
            {"id": "out", "type": "output", "input_var": "context"},
        ]
    },
}


@pytest.fixture
async def client(database):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


async def test_ingested_document_is_retrieved_for_its_owner_only(client):
    ingest = await client.post(
        "/api/v1/collections/policies/documents",
        json={"source": "refunds.md", "text": POLICY},
        headers=ALICE,
    )
    assert ingest.status_code == 201
    assert ingest.json()["chunks"] == 1

    flow_id = (await client.post("/api/v1/flows", json=RAG_FLOW, headers=ALICE)).json()["id"]
    started = await client.post(
        f"/api/v1/flows/{flow_id}/runs", json={"message": POLICY}, headers=ALICE
    )
    run_id = started.json()["id"]
    for _ in range(200):
        run = (await client.get(f"/api/v1/runs/{run_id}", headers=ALICE)).json()
        if run["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.02)

    assert run["status"] == "succeeded", run.get("error")
    assert POLICY in run["output"]["result"]

    other = {"X-Dev-User": "mallory@example.com"}
    other_flow = (await client.post("/api/v1/flows", json=RAG_FLOW, headers=other)).json()["id"]
    other_run = (
        await client.post(
            f"/api/v1/flows/{other_flow}/runs", json={"message": POLICY}, headers=other
        )
    ).json()
    for _ in range(200):
        result = (await client.get(f"/api/v1/runs/{other_run['id']}", headers=other)).json()
        if result["status"] in {"succeeded", "failed"}:
            break
        await asyncio.sleep(0.02)
    assert POLICY not in (result["output"] or {}).get("result", "")
