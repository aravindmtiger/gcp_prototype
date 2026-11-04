"""Turns an approved agent into a running endpoint.

* ``DEPLOY_BACKEND=local``: returns a fake local URL and identity. For development and tests.
* ``DEPLOY_BACKEND=gcp``: deploys to Cloud Run or Vertex AI Agent Runtime (see gcp_deploy.py).
"""

from dataclasses import dataclass
from typing import Protocol

from app.config import Settings
from app.services.gcp_deploy import (
    DeploymentError,
    deploy_to_agent_runtime,
    deploy_to_cloud_run,
    missing_settings,
)

__all__ = ["DeploymentError", "DeployRequest", "DeployResult", "build_deployer"]


@dataclass(frozen=True)
class DeployRequest:
    deployment_id: str
    agent_name: str
    adk_source: str
    target: str
    session_backend: str
    memory_backend: str
    owner_email: str


@dataclass(frozen=True)
class DeployResult:
    endpoint_url: str
    agent_identity: str


class Deployer(Protocol):
    async def deploy(self, request: DeployRequest) -> DeployResult: ...


class LocalDeployer:
    async def deploy(self, request: DeployRequest) -> DeployResult:
        return DeployResult(
            endpoint_url=f"http://localhost:8080/local-agents/{request.agent_name}",
            agent_identity=f"local-{request.agent_name}@localhost",
        )


class GcpDeployer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def deploy(self, request: DeployRequest) -> DeployResult:
        missing = missing_settings(self._settings)
        if missing:
            raise DeploymentError(f"Set {', '.join(missing)} before deploying to Google Cloud")
        if request.target == "agent_engine":
            url, identity = await deploy_to_agent_runtime(
                self._settings, request.agent_name, request.adk_source
            )
        else:
            url, identity = await deploy_to_cloud_run(
                self._settings, request.agent_name, request.deployment_id, request.adk_source
            )
        return DeployResult(endpoint_url=url, agent_identity=identity)


def build_deployer(settings: Settings) -> Deployer:
    if settings.deploy_backend == "gcp":
        return GcpDeployer(settings)
    return LocalDeployer()
