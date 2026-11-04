"""Error handling.

Pattern (mirrors the original platform's CLAUDE.md rule "NO silent errors"):

1. ``log_error(exc, context=...)`` logs the full traceback with a correlation id.
2. ``sanitize_error_for_user(exc)`` returns a message that is safe to show users.
3. Raise ``HTTPException`` (or ``AppError``) with the sanitized message.

Never log secrets, tokens or raw prompts in ``context``.
"""

import logging
import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app.errors")


class AppError(Exception):
    """Expected, user-facing error with an explicit HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def log_error(exc: BaseException, context: dict[str, Any] | None = None) -> str:
    """Log an exception with context and return a correlation id."""
    error_id = uuid.uuid4().hex[:12]
    logger.error(
        "error_id=%s type=%s context=%s",
        error_id,
        type(exc).__name__,
        context or {},
        exc_info=exc,
    )
    return error_id


def sanitize_error_for_user(exc: BaseException, error_id: str | None = None) -> str:
    """Return a message that is safe to show to end users."""
    if isinstance(exc, AppError):
        return exc.message
    suffix = f" (ref {error_id})" if error_id else ""
    return f"Something went wrong while processing your request{suffix}."


def register_exception_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        error_id = log_error(exc, context={"method": request.method, "path": request.url.path})
        return JSONResponse(
            status_code=500,
            content={"detail": sanitize_error_for_user(exc, error_id)},
        )
