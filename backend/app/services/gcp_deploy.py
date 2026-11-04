"""Google Cloud deployment of an approved agent.

* ``cloud_run``: the ADK source is packaged with a Dockerfile, uploaded to Cloud Storage, built
  by Cloud Build into Artifact Registry, and run on Cloud Run as the shared agent service account.
  Cloud Run services are private unless someone grants public access, so this code grants none.
* ``agent_engine``: the ADK agent is created in Vertex AI Agent Runtime with the Vertex AI SDK.

The agent always calls the Agent Gateway. The generated source names the model ``agent-gateway``.

Not exercised by the test suite yet. Calls go to real Google Cloud APIs when GCP settings are set.
"""

import asyncio
import io
import re
import tarfile
from typing import Any

import httpx
from google.cloud import storage

from app.config import Settings
from app.services.secrets import access_token

CLOUD_BUILD_URL = "https://cloudbuild.googleapis.com/v1"
CLOUD_RUN_URL = "https://run.googleapis.com/v2"
POLL_SECONDS = 10
DEPLOY_TIMEOUT_SECONDS = 1800
RUNTIME_REQUIREMENTS = ["google-adk>=1.0", "google-cloud-aiplatform[agent_engines,adk]>=1.100"]

DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
# ADK loads every folder under /app that has an agent.py and __init__.py.
CMD adk api_server --host 0.0.0.0 --port ${PORT} /app
"""


class DeploymentError(Exception):
    """Expected failure with a message that is safe to show the user. Re-exported by deployer."""


def missing_settings(settings: Settings) -> list[str]:
    checks = {
        "GCP_PROJECT_ID": settings.gcp_project_id,
        "GCS_BUCKET": settings.gcs_bucket,
        "AGENT_RUNTIME_SERVICE_ACCOUNT": settings.agent_runtime_service_account,
    }
    return [name for name, value in checks.items() if not value]


def service_name(agent_name: str) -> str:
    """Cloud Run service names: lowercase letters, digits and hyphens, at most 49 characters."""
    slug = re.sub(r"[^a-z0-9-]+", "-", agent_name.lower()).strip("-")
    return slug[:40] or "agent"


def package_source(adk_source: str) -> bytes:
    """Builds the build context: Dockerfile, requirements, and the agent as an ADK package."""
    files = {
        "Dockerfile": DOCKERFILE,
        "requirements.txt": "\n".join(RUNTIME_REQUIREMENTS) + "\n",
        "agent/__init__.py": "from . import agent\n",
        "agent/agent.py": adk_source,
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


async def _call(method: str, url: str, **kwargs: Any) -> httpx.Response:
    headers = {"Authorization": f"Bearer {await asyncio.to_thread(access_token)}"}
    async with httpx.AsyncClient(timeout=60) as http:
        try:
            return await http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise DeploymentError(
                "Could not reach Google Cloud. Check the network and try again."
            ) from exc


async def _json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = await _call(method, url, **kwargs)
    if response.status_code >= 400:
        detail = response.text[:300]
        raise DeploymentError(f"Google Cloud returned HTTP {response.status_code}: {detail}")
    return response.json() if response.content else {}


async def _wait_until(check, description: str) -> dict[str, Any]:
    """Polls ``check`` until it returns a finished result, or the deploy timeout passes."""
    waited = 0
    while True:
        result = await check()
        if result is not None:
            return result
        if waited >= DEPLOY_TIMEOUT_SECONDS:
            raise DeploymentError(f"Timed out waiting for {description}")
        await asyncio.sleep(POLL_SECONDS)
        waited += POLL_SECONDS


async def _cloud_build(settings: Settings, deployment_id: str, image: str, archive: bytes) -> None:
    bucket_name = settings.gcs_bucket
    object_name = f"agent-builds/{deployment_id}.tar.gz"
    await asyncio.to_thread(_upload, bucket_name, object_name, archive)

    project = settings.gcp_project_id
    operation = await _json(
        "POST",
        f"{CLOUD_BUILD_URL}/projects/{project}/builds",
        json={
            "source": {"storageSource": {"bucket": bucket_name, "object": object_name}},
            "steps": [
                {"name": "gcr.io/cloud-builders/docker", "args": ["build", "-t", image, "."]},
                {"name": "gcr.io/cloud-builders/docker", "args": ["push", image]},
            ],
            "images": [image],
        },
    )
    build_id = operation["metadata"]["build"]["id"]

    async def finished() -> dict[str, Any] | None:
        build = await _json("GET", f"{CLOUD_BUILD_URL}/projects/{project}/builds/{build_id}")
        status = build.get("status")
        if status in ("QUEUED", "WORKING", "PENDING", None):
            return None
        return build

    build = await _wait_until(finished, "the Cloud Build image")
    if build["status"] != "SUCCESS":
        raise DeploymentError(f"Image build finished with status {build['status']}")


def _upload(bucket_name: str, object_name: str, archive: bytes) -> None:
    client = storage.Client()
    client.bucket(bucket_name).blob(object_name).upload_from_string(
        archive, content_type="application/gzip"
    )


async def deploy_to_cloud_run(
    settings: Settings, agent_name: str, deployment_id: str, adk_source: str
) -> tuple[str, str]:
    """Returns (service URL, identity the service runs as)."""
    project, location = settings.gcp_project_id, settings.gcp_location
    service = service_name(agent_name)
    image = (
        f"{location}-docker.pkg.dev/{project}/{settings.gcp_artifact_repo}/"
        f"{service}:{deployment_id[:8]}"
    )
    await _cloud_build(settings, deployment_id, image, package_source(adk_source))

    template = {
        "containers": [{"image": image, "ports": [{"containerPort": 8080}]}],
        "serviceAccount": settings.agent_runtime_service_account,
    }
    parent = f"{CLOUD_RUN_URL}/projects/{project}/locations/{location}/services"
    created = await _call("POST", f"{parent}?serviceId={service}", json={"template": template})
    if created.status_code == 409:  # the agent was deployed before: roll the new revision out
        operation = await _json("PATCH", f"{parent}/{service}", json={"template": template})
    elif created.status_code >= 400:
        raise DeploymentError(
            f"Cloud Run returned HTTP {created.status_code}: {created.text[:300]}"
        )
    else:
        operation = created.json()

    async def finished() -> dict[str, Any] | None:
        status = await _json("GET", f"{CLOUD_RUN_URL}/{operation['name']}")
        return status if status.get("done") else None

    done = await _wait_until(finished, "the Cloud Run revision")
    if "error" in done:
        raise DeploymentError(
            f"Cloud Run rejected the revision: {done['error'].get('message', 'unknown error')}"
        )

    current = await _json("GET", f"{parent}/{service}")
    return current["uri"], settings.agent_runtime_service_account


def _create_agent_engine(settings: Settings, agent_name: str, adk_source: str) -> str:
    """Creates the agent in Vertex AI Agent Runtime. Blocking: run it in a worker thread."""
    import vertexai
    from vertexai import agent_engines

    vertexai.init(
        project=settings.gcp_project_id,
        location=settings.gcp_location,
        staging_bucket=f"gs://{settings.gcs_bucket}",
    )
    # The generated module only defines root_agent from escaped strings. It is loaded here so the
    # SDK can pickle the agent object.
    namespace: dict[str, Any] = {}
    exec(compile(adk_source, f"{service_name(agent_name)}.py", "exec"), namespace)  # noqa: S102
    app = agent_engines.AdkApp(agent=namespace["root_agent"])
    remote = agent_engines.create(
        agent_engine=app,
        requirements=RUNTIME_REQUIREMENTS,
        display_name=agent_name,
        service_account=settings.agent_runtime_service_account,
    )
    return remote.resource_name


async def deploy_to_agent_runtime(
    settings: Settings, agent_name: str, adk_source: str
) -> tuple[str, str]:
    """Returns (resource endpoint, identity the agent runs as)."""
    resource_name = await asyncio.to_thread(_create_agent_engine, settings, agent_name, adk_source)
    endpoint = f"https://{settings.gcp_location}-aiplatform.googleapis.com/v1/{resource_name}"
    return endpoint, settings.agent_runtime_service_account
