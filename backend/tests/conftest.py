"""Test environment.

Environment variables are set before the app is imported so tests never read the
developer's .env and never call Google Cloud: SQLite instead of Cloud SQL, the mock
LLM, dev auth and inline run dispatch.
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="agentflow-tests-")
os.environ.update(
    {
        "APP_ENV": "local",
        "LOG_LEVEL": "WARNING",
        "AUTH_MODE": "dev",
        "LLM_PROVIDER": "mock",
        # Set TEST_DATABASE_URL to a PostgreSQL+pgvector URL to run the integration tests.
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL")
        or f"sqlite+aiosqlite:///{_TMP}/test.db",
        "DB_AUTO_CREATE": "true",
        "REDIS_URL": "",
        "TASK_BACKEND": "inline",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": f"{_TMP}/storage",
        "PII_REDACTION_ENABLED": "true",
        "OTEL_ENABLED": "false",
        "CORS_ORIGINS": "http://localhost:5173",
    }
)

import pytest  # noqa: E402

from app.db import dispose_engine, engine, init_db  # noqa: E402
from app.models import Base  # noqa: E402


@pytest.fixture
async def database():
    """Fresh schema for every test; the engine is disposed so pooled connections
    do not leak across pytest-asyncio event loops."""
    tables = _sqlite_tables() if engine.dialect.name == "sqlite" else None
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Base.metadata.drop_all(sync_conn, tables=tables))
    await init_db()
    yield
    await dispose_engine()


def _sqlite_tables():
    return [t for t in Base.metadata.sorted_tables if t.name != "document_chunks"]
