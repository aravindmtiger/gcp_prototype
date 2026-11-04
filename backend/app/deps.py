"""FastAPI dependencies shared by the routers."""

from collections.abc import Awaitable, Callable
from typing import Annotated

import httpx
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, get_current_user, require_role
from app.db import get_session
from app.errors import AppError
from app.models import Flow
from app.services.secrets import read_secret

SecretReader = Callable[[str], Awaitable[str]]

DbSession = Annotated[AsyncSession, Depends(get_session)]
User = Annotated[CurrentUser, Depends(get_current_user)]
# Any signed-in user can build. Only platform admins manage users and review other people's agents.
Builder = Annotated[CurrentUser, Depends(require_role("platform_user", "platform_admin"))]
Admin = Annotated[CurrentUser, Depends(require_role("platform_admin"))]


def get_redis(request: Request) -> Redis | None:
    return request.app.state.redis


RedisClient = Annotated[Redis | None, Depends(get_redis)]


async def load_flow_for_user(session: AsyncSession, user: CurrentUser, flow_id: str) -> Flow:
    """Return the flow if the caller owns it (or is an admin). Otherwise 404, never 403,
    so flow ids cannot be probed."""
    flow = await session.get(Flow, flow_id)
    if flow is None or (flow.owner_email != user.email and not user.is_admin):
        raise AppError(404, "Flow not found")
    return flow


def get_secret_reader() -> SecretReader:
    return read_secret


SecretsReader = Annotated[SecretReader, Depends(get_secret_reader)]


def get_mcp_transport() -> httpx.AsyncBaseTransport | None:
    """None uses the network. Tests replace it with a mock transport."""
    return None


McpTransport = Annotated[httpx.AsyncBaseTransport | None, Depends(get_mcp_transport)]
