"""Startup data that every user can see.

The default guardrail is attached to agents that do not pick a template, so it must
exist before the first agent is submitted for review.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AppUser, GuardrailTemplate

SYSTEM_OWNER = "system@agentflow.local"
DEFAULT_GUARDRAIL_NAME = "default-model-armor"
DEFAULT_GUARDRAIL_CONFIG = {
    "protections": ["prompt_injection", "jailbreak"],
    "info_types": [],
    "custom_infotypes": [],
}


async def ensure_default_guardrail(session: AsyncSession) -> None:
    existing = await session.execute(
        select(GuardrailTemplate).where(
            GuardrailTemplate.owner_email == SYSTEM_OWNER,
            GuardrailTemplate.is_default.is_(True),
        )
    )
    template = existing.scalars().first()
    if template is not None:
        # Keep the seeded default in step with DEFAULT_GUARDRAIL_CONFIG on every start.
        template.config = DEFAULT_GUARDRAIL_CONFIG
        await session.commit()
        return
    session.add(
        GuardrailTemplate(
            owner_email=SYSTEM_OWNER,
            name=DEFAULT_GUARDRAIL_NAME,
            provider="model_armor",
            config=DEFAULT_GUARDRAIL_CONFIG,
            is_default=True,
        )
    )
    await session.commit()


async def ensure_default_admins(session: AsyncSession, settings: Settings) -> None:
    """The default account starts as admin, so someone can manage users on a fresh install.

    Only missing rows are added. An admin who was later changed to another role stays changed.
    """
    emails = set(settings.admin_email_set)
    if settings.auth_mode == "dev":
        emails.add(settings.dev_user_email.lower())
    for email in sorted(emails):
        if await session.get(AppUser, email) is None:
            session.add(AppUser(email=email, role="platform_admin"))
    await session.commit()
