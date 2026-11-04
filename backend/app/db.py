"""Database engine and session management.

Production uses Cloud SQL for PostgreSQL with the pgvector extension. Locally the
same code runs against the docker-compose Postgres container. ``DATABASE_URL``
examples are in ``.env.example``.
"""

import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)


def build_engine(database_url: str, pool_size: int) -> AsyncEngine:
    kwargs: dict = {"pool_pre_ping": True}
    if not database_url.startswith("sqlite"):
        kwargs["pool_size"] = pool_size
    return create_async_engine(database_url, **kwargs)


_settings = get_settings()
engine: AsyncEngine = build_engine(_settings.database_url, _settings.db_pool_size)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


# (table, column, column definition) for columns added to tables that already exist in deployments.
ADDED_COLUMNS = [
    ("mcp_servers", "endpoint_url", "VARCHAR(2000) NOT NULL DEFAULT ''"),
    ("mcp_servers", "auth_type", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
    ("mcp_servers", "auth_config", "JSON NOT NULL DEFAULT '{}'"),
    ("mcp_servers", "last_error", "TEXT NOT NULL DEFAULT ''"),
    ("app_users", "google_subject", "VARCHAR(255)"),
    ("agent_drafts", "architecture", "JSON"),
    ("agent_drafts", "adk_graph", "JSON"),
]

# Role names from the first RBAC release, mapped to the current two roles.
RENAMED_ROLES = [
    ("platform_admin", "admin"),
    ("platform_user", "builder"),
    ("platform_user", "viewer"),
]


async def init_db() -> None:
    """Create the pgvector extension and all tables (idempotent)."""
    is_postgres = engine.dialect.name == "postgresql"
    async with engine.begin() as conn:
        if is_postgres:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        tables = [
            table
            for table in Base.metadata.sorted_tables
            # document_chunks needs pgvector; SQLite test runs skip it.
            if is_postgres or table.name != "document_chunks"
        ]
        await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables))
        if is_postgres:
            # create_all never alters a table that already exists, so columns added after the
            # first release are added here. Each statement is idempotent.
            for table, column, ddl in ADDED_COLUMNS:
                statement = f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"
                await conn.execute(text(statement))
            # Agent names became unique across owners. Older databases have a per-owner constraint.
            await conn.execute(
                text("ALTER TABLE agent_drafts DROP CONSTRAINT IF EXISTS uq_agent_owner_name")
            )
            await conn.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_name ON agent_drafts (name)")
            )
            for new_role, old_role in RENAMED_ROLES:
                await conn.execute(
                    text("UPDATE app_users SET role = :new WHERE role = :old"),
                    {"new": new_role, "old": old_role},
                )
    logger.info("Database schema ready (dialect=%s)", engine.dialect.name)


async def check_db() -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    await engine.dispose()
