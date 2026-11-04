"""Authentication and authorization helpers.

* ``AUTH_MODE=google``: the browser sends a Google ID token (from Google Identity
  Services) as ``Authorization: Bearer <token>``. We verify signature, audience,
  issuer and expiry with google-auth, then apply the email-domain allowlist.
* ``AUTH_MODE=dev``: the caller identifies itself with ``X-Dev-User``. Local only;
  the settings validator refuses this mode when ``APP_ENV=production``.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import AppUser

logger = logging.getLogger(__name__)

# platform_admin manages users and reviews any agent. platform_user builds and approves own agents.
ROLES = ("platform_admin", "platform_user")


@dataclass(frozen=True)
class CurrentUser:
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "platform_admin"


async def register_google_user(
    session: AsyncSession, settings: Settings, email: str, subject: str
) -> str:
    """Registers a Google sign-in on first use with the default role, and returns the role.

    Signing in with Google is how people register. The row keeps the Google subject ID.
    """
    row = await session.get(AppUser, email)
    if row is None:
        default = (
            "platform_admin" if email in settings.admin_email_set else settings.default_user_role
        )
        row = AppUser(email=email, role=default, google_subject=subject)
        session.add(row)
        await session.commit()
    elif row.google_subject != subject:
        row.google_subject = subject
        await session.commit()
    return await role_for(session, settings, email)


async def role_for(session: AsyncSession, settings: Settings, email: str) -> str:
    """ADMIN_EMAILS always wins, so no admin is locked out. The users table decides for others."""
    if email in settings.admin_email_set:
        return "platform_admin"
    row = await session.get(AppUser, email)
    return row.role if row is not None else settings.default_user_role


def require_role(*allowed: str) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Dependency that rejects users whose role is not in ``allowed``."""

    async def check(user: "CurrentUser" = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role does not allow this action")
        return user

    return check


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return token.strip()


async def _verify_google(token: str, audience: str) -> dict:
    try:
        # google-auth fetches and caches Google's public certs; run it off the event loop.
        claims = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            token,
            google_requests.Request(),
            audience,
        )
    except ValueError as exc:
        logger.warning("Rejected Google ID token: %s", exc)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return claims


async def require_task_invoker(request: Request) -> None:
    """Accept only OIDC tokens minted for Cloud Tasks' invoker service account.

    The backend is publicly reachable (it authenticates end users itself), so Cloud
    Run IAM alone would not protect internal routes. This check does."""
    settings = get_settings()
    if not settings.cloud_tasks_invoker_sa:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    audience = settings.backend_public_url.rstrip("/")
    claims = await _verify_google(_bearer_token(request), audience)
    if claims.get("email") != settings.cloud_tasks_invoker_sa or not claims.get("email_verified"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Caller is not the Cloud Tasks invoker")


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    if settings.auth_mode == "dev":
        email = (request.headers.get("X-Dev-User") or settings.dev_user_email).lower()
        return CurrentUser(email=email, role=await role_for(session, settings, email))

    claims = await _verify_google(_bearer_token(request), settings.google_client_id)
    email = str(claims.get("email", "")).lower()
    if not email or not claims.get("email_verified"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google account email is not verified")

    domain = email.rsplit("@", 1)[-1]
    if settings.allowed_domain_set and domain not in settings.allowed_domain_set:
        logger.warning("Blocked sign-in from domain %s", domain)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your email domain is not allowed")

    role = await register_google_user(session, settings, email, str(claims.get("sub", "")))
    return CurrentUser(email=email, role=role)
