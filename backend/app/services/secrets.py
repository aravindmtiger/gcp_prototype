"""Reads Secret Manager secret versions with the backend's own identity (ADC).

Only references are stored in the database. The value is read when a server is connected,
and it is never returned to the browser or written to logs.
"""

import asyncio
import base64

import google.auth
import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request

SECRET_MANAGER_URL = "https://secretmanager.googleapis.com/v1"


class SecretUnavailable(Exception):
    """A message that is safe to show to the user."""


def access_token() -> str:
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())
    return credentials.token


async def read_secret(resource: str) -> str:
    """Return the value of a secret. Without a version, the latest one is read."""
    name = resource if "/versions/" in resource else f"{resource}/versions/latest"
    try:
        token = await asyncio.to_thread(access_token)
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.get(
                f"{SECRET_MANAGER_URL}/{name}:access", headers={"Authorization": f"Bearer {token}"}
            )
    except (GoogleAuthError, httpx.HTTPError) as exc:
        raise SecretUnavailable("The backend could not reach Secret Manager") from exc
    if response.status_code != 200:
        raise SecretUnavailable(
            f"Secret Manager returned HTTP {response.status_code} for {resource}. "
            "Check the secret exists and the backend service account can read it."
        )
    return base64.b64decode(response.json()["payload"]["data"]).decode("utf-8")
