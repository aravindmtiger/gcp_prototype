"""Hands a queued run to the executor.

* ``TASK_BACKEND=inline``: start an asyncio task in this process. Simple for local
  development. On Cloud Run this needs ``--no-cpu-throttling`` so the CPU stays
  allocated after the HTTP response is sent.
* ``TASK_BACKEND=cloud_tasks``: create a Cloud Tasks HTTP task that POSTs to
  ``/internal/runs/{run_id}/execute`` on this service. Cloud Tasks retries failed
  deliveries, so the executor is idempotent (it only starts runs that are ``queued``).
"""

import asyncio
import logging

from app.config import Settings, get_settings
from app.errors import log_error
from app.services.executor import execute_run

logger = logging.getLogger(__name__)

_inflight: set[asyncio.Task] = set()


async def dispatch_run(run_id: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if settings.task_backend == "cloud_tasks":
        await asyncio.to_thread(_enqueue_cloud_task, run_id, settings)
        return
    _start_inline(run_id)


def _start_inline(run_id: str) -> None:
    task = asyncio.create_task(_guarded_execute(run_id))
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


async def _guarded_execute(run_id: str) -> None:
    try:
        await execute_run(run_id)
    except Exception as exc:  # executor records its own failures; this catches bugs in it
        log_error(exc, context={"run_id": run_id, "stage": "inline_dispatch"})


def _enqueue_cloud_task(run_id: str, settings: Settings) -> None:
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(
        settings.gcp_project_id, settings.cloud_tasks_location, settings.cloud_tasks_queue
    )
    url = f"{settings.backend_public_url.rstrip('/')}/internal/runs/{run_id}/execute"
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "oidc_token": {
                "service_account_email": settings.cloud_tasks_invoker_sa,
                "audience": settings.backend_public_url.rstrip("/"),
            },
        }
    }
    created = client.create_task(request={"parent": parent, "task": task})
    logger.info("Enqueued run %s as Cloud Task %s", run_id, created.name)
