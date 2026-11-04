"""Starting runs, polling run status, and the internal endpoint used by Cloud Tasks."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.auth import require_task_invoker
from app.config import get_settings
from app.deps import Builder, DbSession, RedisClient, User, load_flow_for_user
from app.errors import AppError
from app.models import Run
from app.schemas import RunCreate, RunOut
from app.services.cache import enforce_run_rate_limit
from app.services.dispatcher import dispatch_run
from app.services.executor import execute_run

router = APIRouter(tags=["runs"])


@router.post(
    "/api/v1/flows/{flow_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    flow_id: str,
    payload: RunCreate,
    session: DbSession,
    user: Builder,
    redis: RedisClient,
) -> Run:
    settings = get_settings()
    flow = await load_flow_for_user(session, user, flow_id)
    await enforce_run_rate_limit(redis, user.email, settings.rate_limit_runs_per_minute)

    run = Run(flow_id=flow.id, owner_email=user.email, input_message=payload.message)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    await dispatch_run(run.id, settings)
    return run


@router.get("/api/v1/flows/{flow_id}/runs", response_model=list[RunOut])
async def list_runs(flow_id: str, session: DbSession, user: User) -> list[Run]:
    flow = await load_flow_for_user(session, user, flow_id)
    statement = select(Run).where(Run.flow_id == flow.id).order_by(Run.created_at.desc()).limit(50)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.get("/api/v1/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, session: DbSession, user: User) -> Run:
    run = await session.get(Run, run_id)
    if run is None or (run.owner_email != user.email and not user.is_admin):
        raise AppError(404, "Run not found")
    return run


@router.post(
    "/internal/runs/{run_id}/execute",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    dependencies=[Depends(require_task_invoker)],
)
async def execute_run_task(run_id: str) -> dict[str, str]:
    """Target of Cloud Tasks. Only the Cloud Tasks invoker service account's OIDC token
    is accepted (see require_task_invoker). The executor is awaited here so the Cloud
    Tasks attempt reflects the real outcome and retries on crashes."""
    await execute_run(run_id)
    return {"run_id": run_id}
