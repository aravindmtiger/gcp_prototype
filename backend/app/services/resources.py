"""Ownership rules shared by the studio routers.

Same rule as flows: a user sees their own rows (admins see all), and a foreign id
returns 404 so that ids cannot be probed. The default guardrails are the one exception,
because every user may attach them.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.errors import AppError
from app.models import Base, GuardrailTemplate
from app.services.seed import SYSTEM_OWNER


async def get_owned[M: Base](
    session: AsyncSession, model: type[M], user: CurrentUser, item_id: str, label: str
) -> M:
    item = await session.get(model, item_id)
    if item is None or (item.owner_email != user.email and not user.is_admin):
        raise AppError(404, f"{label} not found")
    return item


async def get_visible_guardrail(
    session: AsyncSession, user: CurrentUser, template_id: str
) -> GuardrailTemplate:
    template = await session.get(GuardrailTemplate, template_id)
    visible = template is not None and (
        template.owner_email in {user.email, SYSTEM_OWNER} or user.is_admin
    )
    if not visible:
        raise AppError(404, "Guardrail template not found")
    return template


async def default_guardrail(session: AsyncSession) -> GuardrailTemplate:
    result = await session.execute(
        select(GuardrailTemplate).where(
            GuardrailTemplate.owner_email == SYSTEM_OWNER,
            GuardrailTemplate.is_default.is_(True),
        )
    )
    template = result.scalars().first()
    if template is None:
        raise AppError(500, "Default guardrail is missing; restart the API to seed it")
    return template
