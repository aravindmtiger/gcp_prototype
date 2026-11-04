"""Guardrails Studio: Model Armor and Sensitive Data Protection templates."""

from fastapi import APIRouter, status
from sqlalchemy import or_, select

from app.deps import Builder, DbSession, User
from app.models import GuardrailTemplate
from app.schemas import GuardrailIn, GuardrailOut
from app.services.seed import SYSTEM_OWNER

router = APIRouter(prefix="/api/v1/guardrails", tags=["guardrails"])


def _to_config(payload: GuardrailIn) -> dict:
    return {
        "protections": payload.protections,
        "info_types": payload.info_types,
        "custom_infotypes": [c.model_dump() for c in payload.custom_infotypes],
    }


@router.get("", response_model=list[GuardrailOut])
async def list_guardrails(session: DbSession, user: User) -> list[GuardrailTemplate]:
    # Own templates plus the system defaults, which every user may attach.
    statement = (
        select(GuardrailTemplate)
        .where(
            or_(
                GuardrailTemplate.owner_email == user.email,
                GuardrailTemplate.owner_email == SYSTEM_OWNER,
            )
        )
        .order_by(GuardrailTemplate.created_at.desc())
    )
    return list((await session.execute(statement)).scalars().all())


@router.post("", response_model=GuardrailOut, status_code=status.HTTP_201_CREATED)
async def create_guardrail(
    payload: GuardrailIn, session: DbSession, user: Builder
) -> GuardrailTemplate:
    template = GuardrailTemplate(
        owner_email=user.email,
        name=payload.name,
        provider=",".join(sorted(payload.providers)),
        config=_to_config(payload),
        is_default=False,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template
