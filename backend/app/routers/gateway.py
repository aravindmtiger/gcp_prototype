"""Agent Gateway endpoint: a deployed agent sends a prompt, the gateway returns the reply.

Each reply names the model that was used. Users never pick the model.
"""

import logging

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.deps import DbSession, User
from app.errors import AppError, log_error
from app.models import AgentDraft
from app.services.gateway import (
    AgentGateway,
    GatewayUnavailable,
    GuardrailBlocked,
    get_gateway,
)
from app.services.resources import get_owned

router = APIRouter(prefix="/api/v1/gateway", tags=["gateway"])
logger = logging.getLogger(__name__)


class PromptIn(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


class PromptOut(BaseModel):
    text: str
    model: str
    complexity: str
    screened: bool


def _instruction(agent: AgentDraft) -> str:
    prompts = [node.get("system_prompt", "") for node in agent.workflow.get("nodes", [])]
    return "\n\n".join(p for p in prompts if p)


@router.post("/agents/{agent_id}/prompt", response_model=PromptOut, status_code=status.HTTP_200_OK)
async def prompt_agent(
    agent_id: str,
    payload: PromptIn,
    session: DbSession,
    user: User,
    gateway: AgentGateway = Depends(get_gateway),
) -> PromptOut:
    agent = await get_owned(session, AgentDraft, user, agent_id, "Agent")
    if agent.status != "deployed":
        raise AppError(409, "Only deployed agents can receive prompts through the gateway")

    require_screening = get_settings().app_env == "production"
    try:
        reply = await gateway.handle(payload.message, _instruction(agent), require_screening)
    except GuardrailBlocked as exc:
        raise AppError(403, f"Prompt blocked by the agent's guardrail: {exc}") from exc
    except GatewayUnavailable as exc:
        raise AppError(503, str(exc)) from exc
    except Exception as exc:  # model or screening failure: log with an id, show a generic message
        error_id = log_error(exc, context={"agent_id": agent.id})
        raise AppError(502, f"The model could not answer (ref {error_id})") from exc

    return PromptOut(
        text=reply.text,
        model=reply.model,
        complexity=reply.complexity.name.lower(),
        screened=reply.screened,
    )
