"""Flow CRUD: create, list, read, update and delete agentflows."""

from fastapi import APIRouter, status
from sqlalchemy import select

from app.deps import Builder, DbSession, User, load_flow_for_user
from app.models import Flow, utcnow
from app.schemas import FlowCreate, FlowOut, FlowUpdate

router = APIRouter(prefix="/api/v1/flows", tags=["flows"])


@router.get("", response_model=list[FlowOut])
async def list_flows(session: DbSession, user: User) -> list[Flow]:
    statement = select(Flow).order_by(Flow.updated_at.desc())
    if not user.is_admin:
        statement = statement.where(Flow.owner_email == user.email)
    result = await session.execute(statement)
    return list(result.scalars().all())


@router.post("", response_model=FlowOut, status_code=status.HTTP_201_CREATED)
async def create_flow(payload: FlowCreate, session: DbSession, user: Builder) -> Flow:
    flow = Flow(
        owner_email=user.email,
        name=payload.name,
        description=payload.description,
        definition=payload.definition.model_dump(),
    )
    session.add(flow)
    await session.commit()
    await session.refresh(flow)
    return flow


@router.get("/{flow_id}", response_model=FlowOut)
async def get_flow(flow_id: str, session: DbSession, user: User) -> Flow:
    return await load_flow_for_user(session, user, flow_id)


@router.put("/{flow_id}", response_model=FlowOut)
async def update_flow(flow_id: str, payload: FlowUpdate, session: DbSession, user: Builder) -> Flow:
    flow = await load_flow_for_user(session, user, flow_id)
    if payload.name is not None:
        flow.name = payload.name
    if payload.description is not None:
        flow.description = payload.description
    if payload.definition is not None:
        flow.definition = payload.definition.model_dump()
    flow.updated_at = utcnow()
    await session.commit()
    await session.refresh(flow)
    return flow


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(flow_id: str, session: DbSession, user: Builder) -> None:
    flow = await load_flow_for_user(session, user, flow_id)
    await session.delete(flow)
    await session.commit()
