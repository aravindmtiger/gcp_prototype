"""Redis (Memorystore) access and per-user rate limiting.

If REDIS_URL is empty the limiter is disabled. If Redis errors at runtime the request
is allowed through and the failure is logged: a cache outage must not become an API
outage.
"""

import logging
import time

from fastapi import HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings
from app.errors import log_error

logger = logging.getLogger(__name__)


def build_redis(settings: Settings) -> Redis | None:
    if not settings.redis_url:
        return None
    return Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)


async def enforce_run_rate_limit(redis: Redis | None, owner_email: str, limit: int) -> None:
    if redis is None or limit <= 0:
        return

    window = int(time.time() // 60)
    key = f"ratelimit:runs:{owner_email}:{window}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 60)
    except RedisError as exc:
        log_error(exc, context={"operation": "rate_limit", "owner": owner_email})
        return

    if count > limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Run limit of {limit} per minute reached. Try again shortly.",
        )
