"""Lists resources that already exist in the GCP project, so forms offer them as choices.

* MCP endpoints: Cloud Run services and their URLs.
* RAG corpora: Vertex AI RAG corpora in ``GCP_LOCATION``.
* Structured tables: BigQuery tables in the project.

Calls go to real Google Cloud APIs, so they need ``GCP_PROJECT_ID``. They are not exercised by the
test suite yet.
"""

import asyncio
from typing import Any

import httpx

from app.config import Settings
from app.services.secrets import access_token

RUN_URL = "https://run.googleapis.com/v2"
BIGQUERY_URL = "https://bigquery.googleapis.com/bigquery/v2"
CLOUD_TRACE_URL = "https://cloudtrace.googleapis.com/v1"
MAX_DATASETS = 50


class CatalogError(Exception):
    """A message that is safe to show the user, with the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


def require_project(settings: Settings) -> str:
    if not settings.gcp_project_id:
        raise CatalogError("Set GCP_PROJECT_ID to list resources from Google Cloud", 409)
    return settings.gcp_project_id


async def _get_pages(
    url: str, items_key: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """GET every page of a Google list API and return the items under ``items_key``."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    token = await asyncio.to_thread(access_token)
    async with httpx.AsyncClient(timeout=30) as http:
        while True:
            query = dict(params or {})
            if page_token:
                query["pageToken"] = page_token
            try:
                response = await http.get(
                    url, params=query, headers={"Authorization": f"Bearer {token}"}
                )
            except httpx.HTTPError as exc:
                raise CatalogError(
                    "Could not reach Google Cloud. Check the network and try again."
                ) from exc
            if response.status_code == 403:
                raise CatalogError("The backend service account cannot list these resources", 403)
            if response.status_code >= 400:
                raise CatalogError(
                    f"Google Cloud returned HTTP {response.status_code}: {response.text[:200]}"
                )
            body = response.json()
            items.extend(body.get(items_key, []))
            page_token = body.get("nextPageToken")
            if not page_token:
                return items


async def list_mcp_endpoints(settings: Settings) -> list[dict[str, str]]:
    """Cloud Run services in every region, with the URL each one serves."""
    project = require_project(settings)
    services = await _get_pages(f"{RUN_URL}/projects/{project}/locations/-/services", "services")
    endpoints = []
    for service in services:
        uri = service.get("uri", "")
        if not uri:
            continue
        # Full name looks like projects/<p>/locations/<region>/services/<name>.
        parts = service["name"].split("/")
        endpoints.append({"name": parts[-1], "location": parts[3], "uri": uri})
    return sorted(endpoints, key=lambda e: e["name"])


async def list_rag_corpora(settings: Settings) -> list[dict[str, str]]:
    project = require_project(settings)
    location = settings.gcp_location
    url = f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/ragCorpora"
    corpora = await _get_pages(url, "ragCorpora")
    return sorted(
        (
            {
                "name": corpus["name"],
                "display_name": corpus.get("displayName", corpus["name"].rsplit("/", 1)[-1]),
            }
            for corpus in corpora
        ),
        key=lambda c: c["display_name"],
    )


async def list_bigquery_tables(settings: Settings) -> list[dict[str, str]]:
    """Every table in the project as ``project.dataset.table``."""
    project = require_project(settings)
    datasets = await _get_pages(f"{BIGQUERY_URL}/projects/{project}/datasets", "datasets")
    dataset_ids = [d["datasetReference"]["datasetId"] for d in datasets[:MAX_DATASETS]]

    token = await asyncio.to_thread(access_token)
    headers = {"Authorization": f"Bearer {token}"}
    tables: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=30) as http:
        for dataset_id in dataset_ids:
            response = await http.get(
                f"{BIGQUERY_URL}/projects/{project}/datasets/{dataset_id}/tables", headers=headers
            )
            if response.status_code >= 400:
                continue  # a dataset the backend cannot read is skipped, not fatal
            for table in response.json().get("tables", []):
                ref = table["tableReference"]
                tables.append(
                    {
                        "table_ref": f"{ref['projectId']}.{ref['datasetId']}.{ref['tableId']}",
                        "type": table.get("type", "TABLE"),
                    }
                )
    return sorted(tables, key=lambda t: t["table_ref"])


async def list_cloud_traces(settings: Settings, limit: int = 50) -> list[dict[str, Any]]:
    """Recent traces from Cloud Trace, one row per trace with its root span."""
    project = require_project(settings)
    traces = await _get_pages(
        f"{CLOUD_TRACE_URL}/projects/{project}/traces",
        "traces",
        {"view": "ROOTSPAN", "pageSize": min(limit, 100)},
    )
    rows = []
    for trace in traces[:limit]:
        spans = trace.get("spans", [])
        root = spans[0] if spans else {}
        rows.append(
            {
                "trace_id": trace["traceId"],
                "root_span": root.get("name", ""),
                "start_time": root.get("startTime"),
                "end_time": root.get("endTime"),
            }
        )
    return rows
