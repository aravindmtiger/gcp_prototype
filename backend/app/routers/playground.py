"""Authenticated session and invocation proxy for deployed ADK agents."""

import asyncio
from urllib.parse import quote

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.config import get_settings
from app.deps import DbSession, User
from app.errors import AppError, log_error
from app.models import AgentDraft, Deployment
from app.services.resources import get_owned

router = APIRouter(prefix="/api/v1/agents", tags=["playground"])


class PlaygroundSessionOut(BaseModel):
    session_id: str


class PlaygroundRunIn(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    message: str | None = Field(default=None, min_length=1, max_length=20000)
    choice: str | None = Field(default=None, min_length=1, max_length=100)
    interrupt_id: str | None = Field(default=None, min_length=1, max_length=200)
    function_call_event_id: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _validate_turn(self) -> "PlaygroundRunIn":
        if bool(self.message) == bool(self.choice):
            raise ValueError("send either a message or a HITL choice")
        if bool(self.choice) != bool(self.interrupt_id):
            raise ValueError("a HITL choice must include its interrupt ID")
        return self


async def _latest_deployment(session: DbSession, user: User, agent_id: str) -> Deployment:
    await get_owned(session, AgentDraft, user, agent_id, "Agent")
    statement = (
        select(Deployment)
        .where(Deployment.agent_id == agent_id, Deployment.status == "succeeded")
        .order_by(Deployment.created_at.desc())
    )
    deployment = (await session.execute(statement)).scalars().first()
    if deployment is None or not deployment.endpoint_url:
        raise AppError(409, "Deploy the agent successfully before opening its playground")
    if deployment.target == "cloud_run" and "/local-agents/" in deployment.endpoint_url:
        raise AppError(409, "The local deployment simulator does not expose ADK sessions")
    return deployment


def _agent_engine(resource_url: str):
    import vertexai
    from vertexai import agent_engines

    settings = get_settings()
    vertexai.init(
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        staging_bucket=f"gs://{settings.gcs_bucket}",
    )
    resource_name = resource_url.split("/v1/", 1)[-1]
    return agent_engines.get(resource_name)


async def _cloud_run_request(
    endpoint: str,
    path: str,
    payload: dict,
) -> dict | list:
    from google.auth.exceptions import GoogleAuthError
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import fetch_id_token

    try:
        token = await asyncio.to_thread(fetch_id_token, Request(), endpoint)
    except GoogleAuthError as exc:
        raise AppError(
            503, "The platform could not authenticate to the private agent service"
        ) from exc

    async with httpx.AsyncClient(timeout=180) as client:
        try:
            response = await client.post(
                f"{endpoint.rstrip('/')}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise AppError(502, "Could not reach the deployed ADK service") from exc
    if response.status_code >= 400:
        raise AppError(
            502,
            f"The deployed ADK service returned HTTP {response.status_code}: {response.text[:300]}",
        )
    return response.json() if response.content else {}


@router.post("/{agent_id}/playground/sessions", response_model=PlaygroundSessionOut)
async def create_playground_session(
    agent_id: str, session: DbSession, user: User
) -> PlaygroundSessionOut:
    deployment = await _latest_deployment(session, user, agent_id)
    try:
        if deployment.target == "cloud_run":
            user_id = quote(user.email, safe="")
            created = await _cloud_run_request(
                deployment.endpoint_url,
                f"/apps/agent/users/{user_id}/sessions",
                {"state": {}},
            )
        else:
            remote = await asyncio.to_thread(_agent_engine, deployment.endpoint_url)
            created = await asyncio.to_thread(remote.create_session, user_id=user.email)
    except AppError:
        raise
    except Exception as exc:
        error_id = log_error(exc, context={"agent_id": agent_id})
        raise AppError(502, f"Could not create an ADK session (ref {error_id})") from exc

    session_id = created.get("id") if isinstance(created, dict) else None
    if not session_id:
        raise AppError(502, "The ADK session service did not return a session ID")
    return PlaygroundSessionOut(session_id=str(session_id))


@router.post("/{agent_id}/playground/run")
async def run_playground_turn(
    agent_id: str,
    payload: PlaygroundRunIn,
    session: DbSession,
    user: User,
) -> dict:
    deployment = await _latest_deployment(session, user, agent_id)
    if payload.choice:
        content = {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "id": payload.interrupt_id,
                        "name": "adk_request_input",
                        "response": {"choice": payload.choice},
                    }
                }
            ],
        }
    else:
        content = {"role": "user", "parts": [{"text": payload.message}]}

    try:
        if deployment.target == "cloud_run":
            result = await _cloud_run_request(
                deployment.endpoint_url,
                "/run",
                {
                    "appName": "agent",
                    "userId": user.email,
                    "sessionId": payload.session_id,
                    "newMessage": content,
                    "streaming": False,
                    **(
                        {"functionCallEventId": payload.function_call_event_id}
                        if payload.function_call_event_id
                        else {}
                    ),
                },
            )
        else:
            remote = await asyncio.to_thread(_agent_engine, deployment.endpoint_url)
            stream = remote.async_stream_query(
                user_id=user.email,
                session_id=payload.session_id,
                message=content,
            )
            result = [event async for event in stream]
    except AppError:
        raise
    except Exception as exc:
        error_id = log_error(exc, context={"agent_id": agent_id})
        raise AppError(
            502, f"The deployed agent could not complete the request (ref {error_id})"
        ) from exc

    return {"events": result if isinstance(result, list) else [result]}
