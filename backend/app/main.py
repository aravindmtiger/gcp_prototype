"""FastAPI application factory.

Run locally:   uvicorn app.main:app --reload --port 8080   (from backend/)
Run on Cloud Run: see the Dockerfile; Cloud Run injects PORT.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import SessionLocal, dispose_engine, init_db
from app.errors import register_exception_handlers
from app.logging_setup import setup_logging
from app.observability import configure_observability
from app.routers import (
    agents,
    approvals,
    deployments,
    documents,
    evals,
    flows,
    gateway,
    gcp,
    guardrails,
    health,
    knowledge,
    mcp,
    observability,
    runs,
    users,
)
from app.services.cache import build_redis
from app.services.seed import ensure_default_admins, ensure_default_guardrail

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.db_auto_create:
            await init_db()
            async with SessionLocal() as session:
                await ensure_default_guardrail(session)
                await ensure_default_admins(session, settings)
        app.state.redis = build_redis(settings)
        logger.info(
            "Starting %s (env=%s, auth=%s, llm=%s, tasks=%s, storage=%s)",
            settings.app_name,
            settings.app_env,
            settings.auth_mode,
            settings.llm_provider,
            settings.task_backend,
            settings.storage_backend,
        )
        try:
            yield
        finally:
            if app.state.redis is not None:
                await app.state.redis.aclose()
            await dispose_engine()

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )
    app.state.redis = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # auth uses bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
    )

    register_exception_handlers(app)
    configure_observability(app, settings)

    app.include_router(health.router)
    app.include_router(flows.router)
    app.include_router(runs.router)
    app.include_router(documents.router)
    app.include_router(knowledge.router)
    app.include_router(guardrails.router)
    app.include_router(mcp.router)
    app.include_router(agents.router)
    app.include_router(approvals.router)
    app.include_router(users.router)
    app.include_router(gcp.router)
    app.include_router(evals.router)
    app.include_router(observability.ingest_router)
    app.include_router(observability.router)
    app.include_router(deployments.router)
    app.include_router(gateway.router)
    return app


app = create_app()
