"""Agent Canvas, studios and approvals over HTTP (SQLite, fake approver directory)."""

import ast
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AppUser
from app.services.seed import ensure_default_admins, ensure_default_guardrail

ALICE = {"X-Dev-User": "alice@example.com"}
BOB = {"X-Dev-User": "bob@example.com"}
CAROL = {"X-Dev-User": "carol@example.com"}
RAG_CORPUS = "projects/p1/locations/us-central1/ragCorpora/policies"
CRM_ENDPOINT = "https://crm-abc123-uc.a.run.app/mcp"
CRM_SECRET = "projects/p1/secrets/crm-token/versions/latest"


@pytest.fixture
async def client(database):
    async with SessionLocal() as session:
        await ensure_default_guardrail(session)
        await ensure_default_admins(session, get_settings())
        session.add(AppUser(email="bob@example.com", role="platform_admin"))
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _knowledge(client: AsyncClient, headers: dict, kind: str, config: dict) -> str:
    response = await client.post(
        "/api/v1/knowledge-sources",
        headers=headers,
        json={"name": f"{kind}-src", "kind": kind, "config": config},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _mcp_server(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/api/v1/mcp-servers",
        headers=headers,
        json={"name": "crm", "endpoint_url": CRM_ENDPOINT, "auth_type": "none"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _agent_payload(name: str = "policy_agent", nodes: list[dict] | None = None, **extra) -> dict:
    default_nodes = [
        {
            "id": "kb",
            "tool": "web_search",
            "system_prompt": "Answer from the web.",
            "config": {},
        }
    ]
    return {
        "name": name,
        "description": "Answers policy questions",
        "workflow": {"nodes": nodes or default_nodes},
        **extra,
    }


async def test_default_guardrail_is_visible_to_every_user(client):
    response = await client.get("/api/v1/guardrails", headers=ALICE)
    defaults = [g for g in response.json() if g["is_default"]]
    assert [g["name"] for g in defaults] == ["default-model-armor"]
    assert sorted(defaults[0]["config"]["protections"]) == ["jailbreak", "prompt_injection"]


async def test_guardrail_validation_rules(client):
    rejected = [
        {"name": "a", "providers": ["model_armor"]},  # no protection chosen
        {"name": "b", "providers": ["sdp"]},  # no infotype chosen
        {
            "name": "c",
            "providers": ["sdp"],
            "custom_infotypes": [{"name": "EMP_ID", "regex": "([x"}],
        },
        {"name": "d", "providers": ["model_armor"], "protections": ["jailbreak", "jailbreak"]},
        {
            "name": "e",
            "providers": ["sdp"],
            "protections": ["jailbreak"],
            "info_types": ["EMAIL_ADDRESS"],
        },
        {
            "name": "f",
            "providers": ["model_armor"],
            "protections": ["jailbreak"],
            "info_types": ["EMAIL_ADDRESS"],
        },
        {"name": "g", "providers": []},
        {"name": "h", "providers": ["sdp", "sdp"], "info_types": ["EMAIL_ADDRESS"]},
    ]
    for payload in rejected:
        response = await client.post("/api/v1/guardrails", headers=ALICE, json=payload)
        assert response.status_code == 422, payload

    ok = {"name": "jailbreak-on", "providers": ["model_armor"], "protections": ["jailbreak"]}
    assert (await client.post("/api/v1/guardrails", headers=ALICE, json=ok)).status_code == 201


async def test_model_armor_and_sdp_can_be_combined(client):
    combined = {
        "name": "both",
        "providers": ["sdp", "model_armor"],
        "protections": ["prompt_injection", "jailbreak"],
        "info_types": ["EMAIL_ADDRESS"],
        "custom_infotypes": [{"name": "EMP_ID", "regex": "[A-Z]{2}\\d{6}"}],
    }
    response = await client.post("/api/v1/guardrails", headers=ALICE, json=combined)
    assert response.status_code == 201, response.text
    assert response.json()["providers"] == ["model_armor", "sdp"]

    listed = [
        g
        for g in (await client.get("/api/v1/guardrails", headers=ALICE)).json()
        if g["name"] == "both"
    ]
    assert listed[0]["providers"] == ["model_armor", "sdp"]


async def test_startup_seed_refreshes_an_outdated_default(client):
    from sqlalchemy import select

    from app.models import GuardrailTemplate
    from app.services.seed import SYSTEM_OWNER

    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(GuardrailTemplate).where(GuardrailTemplate.owner_email == SYSTEM_OWNER)
            )
        ).scalar_one()
        row.config = {"protection": "prompt_injection", "info_types": [], "custom_infotypes": []}
        await session.commit()
        await ensure_default_guardrail(session)
        await session.refresh(row)
        assert sorted(row.config["protections"]) == ["jailbreak", "prompt_injection"]


async def test_knowledge_sources_are_validated_per_kind(client):
    bad_table = {
        "name": "t",
        "kind": "structured",
        "config": {"backend": "mysql", "table_ref": "x"},
    }
    bad_corpus = {"name": "c", "kind": "unstructured", "config": {"rag_corpus": "not-a-corpus"}}
    assert (
        await client.post("/api/v1/knowledge-sources", headers=ALICE, json=bad_table)
    ).status_code == 422
    assert (
        await client.post("/api/v1/knowledge-sources", headers=ALICE, json=bad_corpus)
    ).status_code == 422


async def test_mcp_endpoint_and_auth_are_validated(client):
    base = {"name": "crm", "endpoint_url": CRM_ENDPOINT}
    rejected = [
        {**base, "endpoint_url": "http://crm.example.com/mcp"},  # plain http off this machine
        {**base, "auth_type": "bearer_token"},  # needs a secret
        {
            **base,
            "auth_type": "none",
            "secret_name": CRM_SECRET,
        },  # secret without a type that uses one
        {**base, "auth_type": "api_key_header", "secret_name": CRM_SECRET},  # needs a header name
        {
            **base,
            "auth_type": "bearer_token",
            "secret_name": "crm-token",
        },  # not a Secret Manager reference
    ]
    for payload in rejected:
        response = await client.post("/api/v1/mcp-servers", headers=ALICE, json=payload)
        assert response.status_code == 422, payload


async def test_tool_catalog_lists_the_canvas_tools(client):
    ids = [t["id"] for t in (await client.get("/api/v1/tools")).json()]
    assert ids[:7] == [
        "knowledge_retriever",
        "sql_executor",
        "nosql_executor",
        "web_search",
        "email_sender",
        "file_reader",
        "code_executor",
    ]
    assert {"mcp_server", "base", "router", "loop", "if_else", "hitl"}.issubset(set(ids))


async def test_agent_cannot_choose_a_model(client):
    payload = _agent_payload(
        nodes=[{"id": "n", "tool": "web_search", "config": {}, "model": "gemini-2.5-pro"}]
    )
    response = await client.post("/api/v1/agents", headers=ALICE, json=payload)
    assert response.status_code == 422


async def test_agent_tool_must_match_its_source_kind(client):
    structured = await _knowledge(
        client, ALICE, "structured", {"backend": "bigquery", "table_ref": "p.d.orders"}
    )
    nodes = [
        {"id": "sql", "tool": "knowledge_retriever", "config": {"knowledge_source_id": structured}}
    ]
    response = await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload(nodes=nodes))
    assert response.status_code == 422


async def test_create_agent_saves_adk_draft_and_rejects_duplicate_name(client):
    corpus = await _knowledge(client, ALICE, "unstructured", {"rag_corpus": RAG_CORPUS})
    server = await _mcp_server(client, ALICE)
    nodes = [
        {
            "id": "kb",
            "tool": "knowledge_retriever",
            "system_prompt": "Use policies.",
            "config": {"knowledge_source_id": corpus},
        },
        {"id": "crm", "tool": "mcp_server", "config": {"mcp_server_id": server}},
        {"id": "web", "tool": "web_search", "config": {}},
    ]
    response = await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload(nodes=nodes))
    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["status"] == "draft"
    assert agent["guardrail_template_id"] is None
    ast.parse(agent["adk_source"])  # the generated ADK file is valid Python
    assert "LlmAgent(" in agent["adk_source"]
    assert "Workflow(" in agent["adk_source"]
    assert "root_agent = Workflow(" in agent["adk_source"]
    assert "google_search" in agent["adk_source"]

    duplicate = await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())
    assert duplicate.status_code == 409


async def test_other_users_cannot_read_agents(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    assert (await client.get(f"/api/v1/agents/{created['id']}", headers=CAROL)).status_code == 404


async def test_submit_attaches_default_guardrail_and_opens_approval(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    response = await client.post(f"/api/v1/agents/{created['id']}/submit", headers=ALICE)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"

    agent = (await client.get(f"/api/v1/agents/{created['id']}", headers=ALICE)).json()
    assert agent["status"] == "in_review"
    assert agent["guardrail_template_id"] is not None

    # Locked while in review.
    edit = await client.put(
        f"/api/v1/agents/{created['id']}", headers=ALICE, json={"description": "New"}
    )
    assert edit.status_code == 409


async def test_reviewer_approves_and_agent_status_follows(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    approval = (
        await client.post(
            f"/api/v1/agents/{created['id']}/submit",
            headers=ALICE,
        )
    ).json()

    assigned = (await client.get("/api/v1/approvals", headers=BOB)).json()
    assert [a["id"] for a in assigned] == [approval["id"]]
    assert (await client.get("/api/v1/approvals", headers=ALICE)).json() == []

    # A user who is neither the requester nor an admin gets 404, the same as an unknown id.
    denied = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=CAROL, json={"decision": "approve"}
    )
    assert denied.status_code == 404

    decided = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        headers=BOB,
        json={"decision": "approve", "comment": "Looks good"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by"] == "bob@example.com"

    agent = (await client.get(f"/api/v1/agents/{created['id']}", headers=ALICE)).json()
    assert agent["status"] == "approved"

    again = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=BOB, json={"decision": "reject"}
    )
    assert again.status_code == 409


async def test_rejected_agent_can_be_edited_and_resubmitted(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    approval = (
        await client.post(
            f"/api/v1/agents/{created['id']}/submit",
            headers=ALICE,
        )
    ).json()
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=BOB, json={"decision": "reject"}
    )

    edit = await client.put(
        f"/api/v1/agents/{created['id']}", headers=ALICE, json={"description": "Revised"}
    )
    assert edit.status_code == 200
    resubmit = await client.post(f"/api/v1/agents/{created['id']}/submit", headers=ALICE)
    assert resubmit.status_code == 201


async def _approved_agent(client: AsyncClient) -> str:
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    approval = (
        await client.post(
            f"/api/v1/agents/{created['id']}/submit",
            headers=ALICE,
        )
    ).json()
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=BOB, json={"decision": "approve"}
    )
    return created["id"]


async def _wait_for_deployment(client: AsyncClient, deployment_id: str) -> dict:
    for _ in range(200):
        body = (await client.get(f"/api/v1/deployments/{deployment_id}", headers=ALICE)).json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError("deployment did not finish")


async def test_deploy_is_refused_before_approval(client):
    created = (await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload())).json()
    response = await client.post(
        f"/api/v1/agents/{created['id']}/deployments", headers=ALICE, json={"target": "cloud_run"}
    )
    assert response.status_code == 409
    assert "approved" in response.json()["detail"]


async def test_approved_agent_deploys_and_records_identity(client):
    agent_id = await _approved_agent(client)
    response = await client.post(
        f"/api/v1/agents/{agent_id}/deployments",
        headers=ALICE,
        json={"target": "agent_engine", "session_backend": "vertex_ai_session"},
    )
    assert response.status_code == 202, response.text
    body = await _wait_for_deployment(client, response.json()["id"])
    assert body["status"] == "succeeded"
    assert body["endpoint_url"].startswith("http://localhost:8080/local-agents/")
    assert body["agent_identity"].startswith("local-policy_agent@")
    assert body["memory_backend"] == "vertex_ai_memory_bank"

    agent = (await client.get(f"/api/v1/agents/{agent_id}", headers=ALICE)).json()
    assert agent["status"] == "deployed"

    listed = (await client.get(f"/api/v1/agents/{agent_id}/deployments", headers=ALICE)).json()
    assert [d["id"] for d in listed] == [body["id"]]


async def test_gcp_backend_reports_failure_without_pretending(client, monkeypatch):
    from app.services import deployments
    from app.services.deployer import GcpDeployer

    monkeypatch.setattr(deployments, "build_deployer", lambda settings: GcpDeployer(settings))
    agent_id = await _approved_agent(client)
    created = (
        await client.post(
            f"/api/v1/agents/{agent_id}/deployments", headers=ALICE, json={"target": "cloud_run"}
        )
    ).json()
    body = await _wait_for_deployment(client, created["id"])
    assert body["status"] == "failed"
    assert body["error"] == (
        "Set GCP_PROJECT_ID, GCS_BUCKET, AGENT_RUNTIME_SERVICE_ACCOUNT "
        "before deploying to Google Cloud"
    )
    agent = (await client.get(f"/api/v1/agents/{agent_id}", headers=ALICE)).json()
    assert agent["status"] == "approved"


async def test_other_users_cannot_deploy_or_read_deployments(client):
    agent_id = await _approved_agent(client)
    denied = await client.post(
        f"/api/v1/agents/{agent_id}/deployments", headers=CAROL, json={"target": "cloud_run"}
    )
    assert denied.status_code == 404


async def _pending_approval(client: AsyncClient, headers: dict) -> dict:
    created = (await client.post("/api/v1/agents", headers=headers, json=_agent_payload())).json()
    response = await client.post(
        f"/api/v1/agents/{created['id']}/submit",
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_other_users_cannot_approve_someone_elses_agent(client):
    approval = await _pending_approval(client, ALICE)
    other = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=CAROL, json={"decision": "approve"}
    )
    assert other.status_code == 404


async def test_requester_can_approve_own_agent(client):
    approval = await _pending_approval(client, ALICE)
    decided = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision", headers=ALICE, json={"decision": "approve"}
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["decided_by"] == "alice@example.com"
    agent = (await client.get(f"/api/v1/agents/{approval['agent_id']}", headers=ALICE)).json()
    assert agent["status"] == "approved"


async def test_agent_names_are_unique_across_owners(client):
    created = await client.post("/api/v1/agents", headers=ALICE, json=_agent_payload("shared_name"))
    assert created.status_code == 201, created.text

    taken = await client.post("/api/v1/agents", headers=CAROL, json=_agent_payload("shared_name"))
    assert taken.status_code == 409
    assert "already exists" in taken.json()["detail"]

    check = (
        await client.get("/api/v1/agents/name-check", headers=CAROL, params={"name": "shared_name"})
    ).json()
    assert check["available"] is False
    free = (
        await client.get("/api/v1/agents/name-check", headers=CAROL, params={"name": "free_name"})
    ).json()
    assert free["available"] is True
