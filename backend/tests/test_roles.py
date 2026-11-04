"""Roles: the default admin, what each role may do, and who receives approvals."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.services.seed import ensure_default_admins, ensure_default_guardrail

ADMIN = {"X-Dev-User": "dev@example.com"}
ALICE = {"X-Dev-User": "alice@example.com"}
BOB = {"X-Dev-User": "bob@example.com"}


@pytest.fixture
async def client(database):
    async with SessionLocal() as session:
        await ensure_default_guardrail(session)
        await ensure_default_admins(session, get_settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


def _agent() -> dict:
    return {
        "name": "policy_agent",
        "description": "Answers policy questions",
        "workflow": {
            "nodes": [
                {"id": "web_search_1", "tool": "web_search", "system_prompt": "", "config": {}}
            ]
        },
    }


async def _role_of(client: AsyncClient, headers: dict) -> str:
    return (await client.get("/api/v1/me", headers=headers)).json()["role"]


async def test_default_account_is_admin_and_new_users_are_platform_users(client):
    assert await _role_of(client, ADMIN) == "platform_admin"
    assert await _role_of(client, ALICE) == "platform_user"


async def test_only_admins_manage_users(client):
    assert (await client.get("/api/v1/users", headers=ALICE)).status_code == 403
    listed = (await client.get("/api/v1/users", headers=ADMIN)).json()
    assert [u["email"] for u in listed] == ["dev@example.com"]
    assert listed[0]["managed_by_config"] is False


async def test_admin_cannot_change_or_remove_own_role(client):
    own = await client.put(
        "/api/v1/users/dev@example.com", headers=ADMIN, json={"role": "platform_user"}
    )
    assert own.status_code == 409
    removed = await client.delete("/api/v1/users/dev@example.com", headers=ADMIN)
    assert removed.status_code == 409


async def test_admin_changes_another_users_role(client):
    await client.post(
        "/api/v1/users", headers=ADMIN, json={"email": "alice@example.com", "role": "platform_user"}
    )
    changed = await client.put(
        "/api/v1/users/alice@example.com", headers=ADMIN, json={"role": "platform_admin"}
    )
    assert changed.json()["role"] == "platform_admin"
    assert await _role_of(client, ALICE) == "platform_admin"


async def test_submission_reaches_admins_and_requester_or_admin_can_decide(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent())).json()
    submitted = await client.post(f"/api/v1/agents/{created['id']}/submit", headers=ALICE)
    assert submitted.status_code == 201, submitted.text
    approval_id = submitted.json()["id"]
    assert submitted.json()["approver_group"] == "admins"

    # The review queue is for admins only. The requester sees their own request.
    assert (await client.get("/api/v1/approvals", headers=ALICE)).json() == []
    assert [a["id"] for a in (await client.get("/api/v1/approvals", headers=ADMIN)).json()] == [
        approval_id
    ]
    assert [
        a["id"]
        for a in (await client.get("/api/v1/approvals?scope=requested", headers=ALICE)).json()
    ] == [approval_id]

    # Another platform user gets the same 404 as an unknown id.
    other = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", headers=BOB, json={"decision": "approve"}
    )
    assert other.status_code == 404

    decided = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", headers=ADMIN, json={"decision": "approve"}
    )
    assert decided.status_code == 200, decided.text
    agent = (await client.get(f"/api/v1/agents/{created['id']}", headers=ALICE)).json()
    assert agent["status"] == "approved"


async def test_requester_can_approve_their_own_submission(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent())).json()
    submitted = (await client.post(f"/api/v1/agents/{created['id']}/submit", headers=ALICE)).json()
    decided = await client.post(
        f"/api/v1/approvals/{submitted['id']}/decision", headers=ALICE, json={"decision": "approve"}
    )
    assert decided.status_code == 200, decided.text
