"""Approval Studio: agents waiting for an admin, and the reviews you requested.

Every submitted agent goes to the platform admins, and any admin can approve or reject it. The
requester can also approve their own agent. Everyone else gets 404, the same as a missing id, so
approvals cannot be probed.
"""

from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import DbSession, User
from app.errors import AppError
from app.models import AgentDraft, Approval, utcnow
from app.schemas import ApprovalDecision, ApprovalOut

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


async def _with_agent_names(session: DbSession, approvals: list[Approval]) -> list[ApprovalOut]:
    ids = {a.agent_id for a in approvals}
    if not ids:
        return []
    names = dict(
        (
            await session.execute(
                select(AgentDraft.id, AgentDraft.name).where(AgentDraft.id.in_(ids))
            )
        ).all()
    )
    return [ApprovalOut.build(a, names.get(a.agent_id, "(deleted agent)")) for a in approvals]


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    session: DbSession,
    user: User,
    scope: Literal["requested", "assigned"] = Query(default="assigned"),
) -> list[ApprovalOut]:
    if scope == "requested":
        statement = select(Approval).where(Approval.requested_by == user.email)
        found = (
            (await session.execute(statement.order_by(Approval.created_at.desc()))).scalars().all()
        )
        return await _with_agent_names(session, list(found))

    if not user.is_admin:
        return []
    pending = await session.execute(
        select(Approval)
        .where(Approval.status == "pending")
        .order_by(Approval.created_at.desc())
        .limit(200)
    )
    return await _with_agent_names(session, list(pending.scalars().all()))


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
async def decide(
    approval_id: str,
    payload: ApprovalDecision,
    session: DbSession,
    user: User,
) -> ApprovalOut:
    approval = await session.get(Approval, approval_id)
    own_request = approval is not None and approval.requested_by == user.email
    can_decide = own_request or user.is_admin
    if approval is None or not can_decide:
        raise AppError(404, "Approval not found")
    if approval.status != "pending":
        raise AppError(409, f"Approval is already {approval.status}")

    agent = await session.get(AgentDraft, approval.agent_id)
    approval.status = "approved" if payload.decision == "approve" else "rejected"
    approval.decided_by = user.email
    approval.decision_comment = payload.comment
    approval.decided_at = utcnow()
    if agent is not None:
        agent.status = approval.status
    await session.commit()
    await session.refresh(approval)
    return ApprovalOut.build(approval, agent.name if agent else "(deleted agent)")
