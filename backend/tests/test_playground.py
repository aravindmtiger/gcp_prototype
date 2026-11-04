"""ADK Playground session ownership and invocation payloads."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal
from app.main import app
from app.models import Deployment
from app.services.seed import ensure_default_guardrail

ALICE = {"X-Dev-User": "alice@example.com"}


@pytest.fixture
async def client(database):
    async with SessionLocal() as session:
        await ensure_default_guardrail(session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _deployed_agent(client: AsyncClient) -> str:
    response = await client.post(
        "/api/v1/agents",
        headers=ALICE,
        json={
            "name": "playground_agent",
            "description": "Test interactive ADK sessions",
            "workflow": {"nodes": [{"id": "search", "tool": "web_search", "config": {}}]},
        },
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]
    async with SessionLocal() as session:
        session.add(
            Deployment(
                agent_id=agent_id,
                owner_email="alice@example.com",
                target="cloud_run",
                session_backend="in_memory",
                memory_backend="none",
                status="succeeded",
                endpoint_url="https://agent.example.test",
            )
        )
        await session.commit()
    return agent_id


async def test_playground_creates_a_session_and_resumes_hitl_choices(client, monkeypatch):
    from app.routers import playground

    calls = []

    async def cloud_request(endpoint, path, payload):
        calls.append((endpoint, path, payload))
        if path.endswith("/sessions"):
            return {"id": "session-123"}
        return [{"id": "event-1", "content": {"parts": [{"text": "continued"}]}}]

    monkeypatch.setattr(playground, "_cloud_run_request", cloud_request)
    agent_id = await _deployed_agent(client)

    session_response = await client.post(
        f"/api/v1/agents/{agent_id}/playground/sessions", headers=ALICE
    )
    assert session_response.status_code == 200, session_response.text
    assert session_response.json() == {"session_id": "session-123"}
    assert calls[0][1] == "/apps/agent/users/alice%40example.com/sessions"

    resumed = await client.post(
        f"/api/v1/agents/{agent_id}/playground/run",
        headers=ALICE,
        json={
            "session_id": "session-123",
            "choice": "approve",
            "interrupt_id": "hitl:review",
            "function_call_event_id": "event-prompt",
        },
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["events"][0]["content"]["parts"][0]["text"] == "continued"
    run_request = calls[-1][2]
    assert run_request["newMessage"]["parts"][0]["functionResponse"] == {
        "id": "hitl:review",
        "name": "adk_request_input",
        "response": {"choice": "approve"},
    }
    assert run_request["functionCallEventId"] == "event-prompt"


async def test_playground_rejects_users_without_access_to_the_agent(client):
    agent_id = await _deployed_agent(client)
    denied = await client.post(
        f"/api/v1/agents/{agent_id}/playground/sessions",
        headers={"X-Dev-User": "bob@example.com"},
    )
    assert denied.status_code == 404


async def test_playground_requires_exactly_one_of_message_or_choice(client):
    agent_id = await _deployed_agent(client)
    response = await client.post(
        f"/api/v1/agents/{agent_id}/playground/run",
        headers=ALICE,
        json={"session_id": "session-123"},
    )
    assert response.status_code == 422
