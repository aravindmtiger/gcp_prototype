"""Connects to a remote MCP server over Streamable HTTP and lists the tools it offers.

The handshake is the MCP one: initialize, notifications/initialized, then tools/list.
Errors are turned into messages that are safe to show to the user.
"""

import asyncio
import json
from typing import Any

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

PROTOCOL_VERSION = "2025-03-26"
TIMEOUT_SECONDS = 15.0


class McpConnectionError(Exception):
    """A message that is safe to show to the user."""


def endpoint_origin(endpoint: str) -> str:
    parts = httpx.URL(endpoint)
    return f"{parts.scheme}://{parts.host}" + (f":{parts.port}" if parts.port else "")


async def google_id_token(audience: str) -> str:
    """An ID token for the backend's service account, for Cloud Run or IAP-protected servers."""
    try:
        return await asyncio.to_thread(id_token.fetch_id_token, Request(), audience)
    except (GoogleAuthError, OSError) as exc:
        raise McpConnectionError(
            "The backend could not create a Google ID token. "
            "Check its service account and that it can call the server."
        ) from exc


def _parse_body(response: httpx.Response, request_id: int) -> dict[str, Any] | None:
    """Returns the reply for request_id, from a JSON or event-stream body."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                message = json.loads(line[5:].strip())
                if message.get("id") == request_id:
                    return message
        return None
    return response.json() if response.content else None


async def _post(
    http: httpx.AsyncClient, endpoint: str, headers: dict[str, str], payload: dict[str, Any]
) -> httpx.Response:
    try:
        response = await http.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise McpConnectionError("The server did not answer in time") from exc
    except httpx.HTTPError as exc:
        raise McpConnectionError("Could not reach the server. Check the address") from exc
    if response.status_code in (401, 403):
        code = response.status_code
        raise McpConnectionError(f"Credentials rejected by the server (HTTP {code})")
    if response.status_code >= 400:
        raise McpConnectionError(f"The server returned HTTP {response.status_code}")
    return response


async def _request(
    http: httpx.AsyncClient,
    endpoint: str,
    headers: dict[str, str],
    request_id: int,
    method: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    response = await _post(http, endpoint, headers, payload)
    message = _parse_body(response, request_id)
    if message is None:
        raise McpConnectionError(f"The server did not answer {method}")
    if "error" in message:
        detail = message["error"].get("message", "unknown error")
        raise McpConnectionError(f"The server reported an error: {detail}")
    return message.get("result", {}), response.headers.get("mcp-session-id")


async def list_tools(
    endpoint: str, auth_headers: dict[str, str], transport: httpx.AsyncBaseTransport | None = None
) -> list[dict[str, str]]:
    """Runs the handshake and returns each tool's name and description."""
    base = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    base.update(auth_headers)
    async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS) as http:
        _, session_id = await _request(
            http,
            endpoint,
            base,
            1,
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentflow", "version": "1.0.0"},
            },
        )
        session_headers = {**base, **({"mcp-session-id": session_id} if session_id else {})}
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        await _post(http, endpoint, session_headers, initialized)
        result, _ = await _request(http, endpoint, session_headers, 2, "tools/list", {})

    return [
        {"name": tool["name"], "description": tool.get("description", "")}
        for tool in result.get("tools", [])
        if isinstance(tool, dict) and tool.get("name")
    ]
