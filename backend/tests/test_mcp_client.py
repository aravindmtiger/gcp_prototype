"""MCP Client: connecting to a remote MCP server with each auth type. Mock transport, no network."""

import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.deps import get_mcp_transport, get_secret_reader
from app.main import app
from app.services.secrets import SecretUnavailable

ALICE = {"X-Dev-User": "alice@example.com"}
ENDPOINT = "https://crm-abc123-uc.a.run.app/mcp"
SECRET = "projects/p1/secrets/crm-token/versions/latest"
TOOLS = [
    {"name": "lookup_customer", "description": "Find a customer by email"},
    {"name": "open_ticket", "description": "Open a support ticket"},
]


def fake_mcp(
    seen: list[tuple[str | None, str | None]], *, status: int | None = None
) -> httpx.MockTransport:
    """A Streamable HTTP MCP server: initialize, notifications/initialized, tools/list."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        method = body.get("method")
        seen.append((request.headers.get("authorization"), method))
        if status is not None:
            return httpx.Response(status)
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": result},
                headers={"mcp-session-id": "session-1"},
            )
        if method == "notifications/initialized":
            assert request.headers.get("mcp-session-id") == "session-1"
            return httpx.Response(202)
        assert method == "tools/list"
        assert request.headers.get("mcp-session-id") == "session-1"
        # The tools reply comes back as a server-sent event, which the client must also read.
        event = {"jsonrpc": "2.0", "id": body["id"], "result": {"tools": TOOLS}}
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=f"event: message\ndata: {json.dumps(event)}\n\n".encode(),
        )

    return httpx.MockTransport(handler)


@pytest.fixture
async def http(database):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _use(transport: httpx.MockTransport, secrets: dict[str, str] | None = None) -> None:
    async def read_secret(resource: str) -> str:
        if resource not in (secrets or {}):
            raise SecretUnavailable(f"Secret Manager returned HTTP 404 for {resource}.")
        return secrets[resource]

    app.dependency_overrides[get_mcp_transport] = lambda: transport
    app.dependency_overrides[get_secret_reader] = lambda: read_secret


async def _create(http: AsyncClient, **overrides) -> dict:
    payload = {"name": "crm", "endpoint_url": ENDPOINT, "auth_type": "none", **overrides}
    response = await http.post("/api/v1/mcp-servers", headers=ALICE, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_connect_lists_tools_over_the_mcp_handshake(http):
    seen: list[tuple[str | None, str | None]] = []
    _use(fake_mcp(seen))
    server = await _create(http)
    assert server["status"] == "draft" and server["tools"] == []

    connected = await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert connected.status_code == 200, connected.text
    body = connected.json()
    assert body["status"] == "connected"
    assert body["tools"] == TOOLS
    assert body["last_error"] == ""
    assert [method for _, method in seen] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]


async def test_bearer_token_is_read_from_secret_manager_and_never_returned(http):
    seen: list[tuple[str | None, str | None]] = []
    _use(fake_mcp(seen), {SECRET: "tok-123-secret"})
    server = await _create(http, auth_type="bearer_token", secret_name=SECRET)

    connected = await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert connected.json()["status"] == "connected"
    assert all(auth == "Bearer tok-123-secret" for auth, _ in seen)
    # The reference is shown, the value is not.
    assert SECRET in connected.text
    assert "tok-123-secret" not in connected.text


async def test_api_key_is_sent_in_the_chosen_header(http):
    received: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(dict(request.headers))
        return httpx.Response(401)

    _use(httpx.MockTransport(handler), {SECRET: "key-xyz"})
    server = await _create(
        http, auth_type="api_key_header", header_name="X-Api-Key", secret_name=SECRET
    )
    await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert received[0]["x-api-key"] == "key-xyz"


async def test_google_id_token_uses_the_server_origin_as_audience(http, monkeypatch):
    audiences: list[str] = []

    async def fake_token(audience: str) -> str:
        audiences.append(audience)
        return "id-token-abc"

    monkeypatch.setattr("app.routers.mcp.google_id_token", fake_token)
    seen: list[tuple[str | None, str | None]] = []
    _use(fake_mcp(seen))
    server = await _create(http, auth_type="google_id_token")

    connected = await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert connected.json()["status"] == "connected"
    assert audiences == ["https://crm-abc123-uc.a.run.app"]
    assert all(auth == "Bearer id-token-abc" for auth, _ in seen)


async def test_rejected_credentials_are_saved_as_a_readable_error(http):
    _use(fake_mcp([], status=401))
    server = await _create(http)

    failed = await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert failed.status_code == 200
    assert failed.json()["status"] == "error"
    assert failed.json()["last_error"] == "Credentials rejected by the server (HTTP 401)"


async def test_missing_secret_is_reported_on_the_server(http):
    _use(fake_mcp([]), {})
    server = await _create(http, auth_type="bearer_token", secret_name=SECRET)

    failed = await http.post(f"/api/v1/mcp-servers/{server['id']}/connect", headers=ALICE)
    assert failed.json()["status"] == "error"
    assert "HTTP 404" in failed.json()["last_error"]


async def test_other_users_cannot_connect_a_server(http):
    _use(fake_mcp([]))
    server = await _create(http)
    response = await http.post(
        f"/api/v1/mcp-servers/{server['id']}/connect", headers={"X-Dev-User": "bob@example.com"}
    )
    assert response.status_code == 404
