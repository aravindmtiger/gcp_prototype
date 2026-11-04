"""End-to-end API tests against SQLite with the mock LLM and inline dispatch."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

ALICE = {"X-Dev-User": "alice@example.com"}
BOB = {"X-Dev-User": "bob@example.com"}

SIMPLE_FLOW = {
    "name": "Support bot",
    "description": "Answers questions",
    "definition": {
        "nodes": [
            {"id": "in", "type": "chat_input", "output_var": "question"},
            {
                "id": "ask",
                "type": "llm",
                "input_var": "question",
                "output_var": "answer",
                "config": {"system_prompt": "Be brief."},
            },
            {"id": "out", "type": "output", "input_var": "answer"},
        ]
    },
}


@pytest.fixture
async def client(database):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _wait_for_run(client: AsyncClient, run_id: str, headers: dict) -> dict:
    for _ in range(200):
        response = await client.get(f"/api/v1/runs/{run_id}", headers=headers)
        body = response.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError("run did not finish in time")


async def test_health_endpoints_are_public(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    assert (await client.get("/readyz")).status_code == 200


async def test_create_and_read_own_flow(client):
    created = await client.post("/api/v1/flows", json=SIMPLE_FLOW, headers=ALICE)
    assert created.status_code == 201
    flow_id = created.json()["id"]
    assert created.json()["owner_email"] == "alice@example.com"

    fetched = await client.get(f"/api/v1/flows/{flow_id}", headers=ALICE)
    assert fetched.status_code == 200


async def test_other_users_get_404_not_403(client):
    flow_id = (await client.post("/api/v1/flows", json=SIMPLE_FLOW, headers=ALICE)).json()["id"]
    response = await client.get(f"/api/v1/flows/{flow_id}", headers=BOB)
    assert response.status_code == 404
    listing = await client.get("/api/v1/flows", headers=BOB)
    assert listing.json() == []


async def test_invalid_flow_is_rejected_at_save_time(client):
    bad = {
        "name": "Broken",
        "definition": {
            "nodes": [
                {"id": "ask", "type": "llm", "input_var": "missing", "output_var": "a"},
                {"id": "out", "type": "output", "input_var": "a"},
            ]
        },
    }
    response = await client.post("/api/v1/flows", json=bad, headers=ALICE)
    assert response.status_code == 422


async def test_run_executes_and_redacts_pii(client):
    flow_id = (await client.post("/api/v1/flows", json=SIMPLE_FLOW, headers=ALICE)).json()["id"]

    started = await client.post(
        f"/api/v1/flows/{flow_id}/runs",
        json={"message": "Email me at jane.doe@example.com please"},
        headers=ALICE,
    )
    assert started.status_code == 202
    run = await _wait_for_run(client, started.json()["id"], ALICE)

    assert run["status"] == "succeeded"
    assert "jane.doe@example.com" not in run["output"]["result"]
    assert "[EMAIL_REDACTED]" in run["output"]["result"]
    assert [s["node_type"] for s in run["steps"]] == ["chat_input", "llm", "output"]
    assert all(s["status"] == "succeeded" for s in run["steps"])


async def test_failed_model_call_marks_run_failed_with_sanitized_error(client, monkeypatch):
    class BrokenLLM:
        async def generate(self, prompt, system_prompt=""):
            raise RuntimeError("secret upstream detail")

    monkeypatch.setattr("app.services.executor.get_llm_client", lambda: BrokenLLM())
    flow_id = (await client.post("/api/v1/flows", json=SIMPLE_FLOW, headers=ALICE)).json()["id"]
    started = await client.post(
        f"/api/v1/flows/{flow_id}/runs", json={"message": "hi"}, headers=ALICE
    )
    run = await _wait_for_run(client, started.json()["id"], ALICE)

    assert run["status"] == "failed"
    assert "secret upstream detail" not in run["error"]
    assert run["error"].startswith("Something went wrong")
    assert [s["status"] for s in run["steps"]] == ["succeeded", "failed"]


async def test_internal_task_route_is_hidden_without_invoker_config(client):
    response = await client.post("/internal/runs/abc/execute")
    assert response.status_code == 404


async def test_upload_rejects_unsupported_type(client):
    response = await client.post(
        "/api/v1/collections/docs/files",
        files={"file": ("image.png", b"\x89PNG", "image/png")},
        headers=ALICE,
    )
    assert response.status_code == 415
