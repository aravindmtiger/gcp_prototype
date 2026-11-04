"""Google sign-in and Cloud Tasks invoker checks, with Google's verifier mocked out."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import auth
from app.config import Settings


class _FakeUsers:
    """Stands in for the database session. Records added users, so registration can be checked."""

    def __init__(self) -> None:
        self.rows: dict[str, object] = {}
        self.commits = 0

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, row) -> None:
        self.rows[row.email] = row

    async def commit(self) -> None:
        self.commits += 1


NO_USERS = _FakeUsers()


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


def _google_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "auth_mode": "google",
        "google_client_id": "client-id.apps.googleusercontent.com",
        "admin_emails": "boss@example.com",
    }
    values.update(overrides)
    return Settings(**values)


def _patch_verifier(monkeypatch, claims=None, error: Exception | None = None):
    def fake_verify(token, request, audience):
        if error:
            raise error
        return claims

    monkeypatch.setattr(auth.google_id_token, "verify_oauth2_token", fake_verify)


async def test_valid_google_token_yields_user(monkeypatch):
    _patch_verifier(monkeypatch, {"email": "Jane@Example.com", "email_verified": True})
    request = _request({"Authorization": "Bearer abc.def.ghi"})

    user = await auth.get_current_user(request, session=NO_USERS, settings=_google_settings())

    assert user.email == "jane@example.com"
    assert user.is_admin is False


async def test_admin_email_is_flagged(monkeypatch):
    _patch_verifier(monkeypatch, {"email": "boss@example.com", "email_verified": True})
    user = await auth.get_current_user(
        _request({"Authorization": "Bearer t"}), session=NO_USERS, settings=_google_settings()
    )
    assert user.is_admin is True


async def test_domain_allowlist_blocks_other_domains(monkeypatch):
    _patch_verifier(monkeypatch, {"email": "x@other.org", "email_verified": True})
    with pytest.raises(HTTPException) as info:
        await auth.get_current_user(
            _request({"Authorization": "Bearer t"}),
            session=NO_USERS,
            settings=_google_settings(allowed_email_domains="example.com"),
        )
    assert info.value.status_code == 403


async def test_unverified_email_is_rejected(monkeypatch):
    _patch_verifier(monkeypatch, {"email": "x@example.com", "email_verified": False})
    with pytest.raises(HTTPException) as info:
        await auth.get_current_user(
            _request({"Authorization": "Bearer t"}), session=NO_USERS, settings=_google_settings()
        )
    assert info.value.status_code == 403


async def test_invalid_token_is_401(monkeypatch):
    _patch_verifier(monkeypatch, error=ValueError("Token expired"))
    with pytest.raises(HTTPException) as info:
        await auth.get_current_user(
            _request({"Authorization": "Bearer t"}), session=NO_USERS, settings=_google_settings()
        )
    assert info.value.status_code == 401


async def test_missing_bearer_is_401():
    with pytest.raises(HTTPException) as info:
        await auth.get_current_user(_request(), session=NO_USERS, settings=_google_settings())
    assert info.value.status_code == 401


async def test_task_invoker_accepts_only_the_invoker_service_account(monkeypatch):
    settings = _google_settings(
        cloud_tasks_invoker_sa="agentflow-tasks-invoker@p.iam.gserviceaccount.com",
        backend_public_url="https://api.example.run.app/",
    )
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    _patch_verifier(
        monkeypatch,
        {"email": "someone-else@p.iam.gserviceaccount.com", "email_verified": True},
    )
    with pytest.raises(HTTPException) as info:
        await auth.require_task_invoker(_request({"Authorization": "Bearer t"}))
    assert info.value.status_code == 403

    _patch_verifier(
        monkeypatch,
        {"email": "agentflow-tasks-invoker@p.iam.gserviceaccount.com", "email_verified": True},
    )
    await auth.require_task_invoker(_request({"Authorization": "Bearer t"}))


async def test_first_google_sign_in_registers_the_user_with_its_subject(monkeypatch):
    _patch_verifier(
        monkeypatch,
        {"email": "new.person@example.com", "email_verified": True, "sub": "1234567890"},
    )
    users = _FakeUsers()
    user = await auth.get_current_user(
        _request({"Authorization": "Bearer t"}), session=users, settings=_google_settings()
    )
    row = users.rows["new.person@example.com"]
    assert row.google_subject == "1234567890"
    assert row.role == "platform_user"
    assert user.role == "platform_user"


async def test_admin_email_registers_as_platform_admin(monkeypatch):
    _patch_verifier(
        monkeypatch,
        {"email": "boss@example.com", "email_verified": True, "sub": "42"},
    )
    users = _FakeUsers()
    user = await auth.get_current_user(
        _request({"Authorization": "Bearer t"}), session=users, settings=_google_settings()
    )
    assert user.role == "platform_admin"
