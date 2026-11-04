"""MCP Client: connect to MCP servers that already run in Google Cloud and list their tools.

Credentials are never stored here. A server keeps only the auth type, the header name, and a
Secret Manager reference. The value is read when the server is connected.
"""

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import Builder, DbSession, McpTransport, SecretReader, SecretsReader, User
from app.models import McpServer
from app.schemas import McpServerIn, McpServerOut
from app.services.mcp_client import McpConnectionError, endpoint_origin, google_id_token, list_tools
from app.services.resources import get_owned
from app.services.secrets import SecretUnavailable

router = APIRouter(prefix="/api/v1/mcp-servers", tags=["mcp"])


async def _auth_headers(server: McpServer, read_secret: SecretReader) -> dict[str, str]:
    config = server.auth_config or {}
    try:
        if server.auth_type == "google_id_token":
            token = await google_id_token(endpoint_origin(server.endpoint_url))
            return {"Authorization": f"Bearer {token}"}
        if server.auth_type == "bearer_token":
            return {"Authorization": f"Bearer {await read_secret(config['secret_name'])}"}
        if server.auth_type == "api_key_header":
            return {config["header_name"]: await read_secret(config["secret_name"])}
    except SecretUnavailable as exc:
        raise McpConnectionError(str(exc)) from exc
    return {}


@router.get("", response_model=list[McpServerOut])
async def list_servers(session: DbSession, user: User) -> list[McpServer]:
    statement = select(McpServer).order_by(McpServer.created_at.desc())
    if not user.is_admin:
        statement = statement.where(McpServer.owner_email == user.email)
    return list((await session.execute(statement)).scalars().all())


@router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(payload: McpServerIn, session: DbSession, user: Builder) -> McpServer:
    server = McpServer(
        owner_email=user.email,
        name=payload.name,
        description=payload.description,
        endpoint_url=payload.endpoint_url,
        auth_type=payload.auth_type,
        auth_config=payload.auth_config(),
        tools=[],
        status="draft",
        last_error="",
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


@router.get("/{server_id}", response_model=McpServerOut)
async def get_server(server_id: str, session: DbSession, user: User) -> McpServer:
    return await get_owned(session, McpServer, user, server_id, "MCP server")


@router.post("/{server_id}/connect", response_model=McpServerOut)
async def connect_server(
    server_id: str,
    session: DbSession,
    user: Builder,
    read_secret: SecretsReader,
    transport: McpTransport,
) -> McpServer:
    """Runs the MCP handshake and stores the tools. Failures are saved on the server, not raised."""
    server = await get_owned(session, McpServer, user, server_id, "MCP server")
    try:
        headers = await _auth_headers(server, read_secret)
        tools = await list_tools(server.endpoint_url, headers, transport)
    except McpConnectionError as exc:
        server.status = "error"
        server.last_error = str(exc)
    else:
        server.status = "connected"
        server.tools = tools
        server.last_error = ""
    await session.commit()
    await session.refresh(server)
    return server
