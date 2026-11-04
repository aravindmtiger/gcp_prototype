"""Background worker for a deployment: calls the deployer and records the outcome."""

import logging

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.errors import log_error
from app.models import AgentDraft, Deployment, utcnow
from app.services.deployer import DeploymentError, DeployRequest, build_deployer

logger = logging.getLogger(__name__)


async def run_deployment(deployment_id: str) -> None:
    async with SessionLocal() as session:
        deployment = await session.get(Deployment, deployment_id)
        if deployment is None or deployment.status != "queued":
            return  # already handled; the worker is idempotent
        agent = await session.get(AgentDraft, deployment.agent_id)

        deployment.status = "running"
        await session.commit()

        try:
            result = await build_deployer(get_settings()).deploy(
                DeployRequest(
                    deployment_id=deployment.id,
                    agent_name=agent.name,
                    adk_source=agent.adk_source,
                    target=deployment.target,
                    session_backend=deployment.session_backend,
                    memory_backend=deployment.memory_backend,
                    owner_email=deployment.owner_email,
                )
            )
        except DeploymentError as exc:
            deployment.status = "failed"
            deployment.error = str(exc)
        except Exception as exc:  # unexpected: log with an id, show a generic message
            error_id = log_error(exc, context={"deployment_id": deployment_id})
            deployment.status = "failed"
            deployment.error = f"Deployment failed unexpectedly (ref {error_id})"
        else:
            deployment.status = "succeeded"
            deployment.endpoint_url = result.endpoint_url
            deployment.agent_identity = result.agent_identity
            agent.status = "deployed"

        deployment.finished_at = utcnow()
        await session.commit()


async def latest_active(session, agent_id: str) -> Deployment | None:
    statement = select(Deployment).where(
        Deployment.agent_id == agent_id, Deployment.status.in_(["queued", "running"])
    )
    return (await session.execute(statement)).scalars().first()
