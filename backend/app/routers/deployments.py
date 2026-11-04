"""Deployments of approved agents.

The approval gate: an agent can only be deployed once it is ``approved``. Deployment runs
in the background; poll ``GET /api/v1/deployments/{id}`` for the outcome.
"""

import asyncio

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import Builder, DbSession, User
from app.errors import AppError
from app.models import AgentDraft, Deployment
from app.schemas import DeploymentIn, DeploymentOut
from app.services.deployments import latest_active, run_deployment
from app.services.resources import get_owned

router = APIRouter(prefix="/api/v1", tags=["deployments"])

_inflight: set[asyncio.Task] = set()


@router.post(
    "/agents/{agent_id}/deployments",
    response_model=DeploymentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_deployment(
    agent_id: str, payload: DeploymentIn, session: DbSession, user: Builder
) -> Deployment:
    agent = await get_owned(session, AgentDraft, user, agent_id, "Agent")
    if agent.status != "approved":
        raise AppError(
            409, f"Agent must be approved before deployment (status is '{agent.status}')"
        )
    if await latest_active(session, agent.id) is not None:
        raise AppError(409, "A deployment for this agent is already in progress")

    deployment = Deployment(
        agent_id=agent.id,
        owner_email=user.email,
        target=payload.target,
        session_backend=payload.session_backend,
        memory_backend=payload.memory_backend,
        status="queued",
    )
    session.add(deployment)
    await session.commit()
    await session.refresh(deployment)

    task = asyncio.create_task(run_deployment(deployment.id))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)
    return deployment


@router.get("/agents/{agent_id}/deployments", response_model=list[DeploymentOut])
async def list_deployments(agent_id: str, session: DbSession, user: User) -> list[Deployment]:
    agent = await get_owned(session, AgentDraft, user, agent_id, "Agent")
    statement = (
        select(Deployment)
        .where(Deployment.agent_id == agent.id)
        .order_by(Deployment.created_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


@router.get("/deployments/{deployment_id}", response_model=DeploymentOut)
async def get_deployment(deployment_id: str, session: DbSession, user: User) -> Deployment:
    deployment = await session.get(Deployment, deployment_id)
    if deployment is None or (deployment.owner_email != user.email and not user.is_admin):
        raise AppError(404, "Deployment not found")
    return deployment
