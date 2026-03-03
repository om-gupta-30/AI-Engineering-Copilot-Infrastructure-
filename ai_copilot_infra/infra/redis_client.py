"""
Redis async client factory and connection pool management.
Uses redis-py with hiredis parser for performance.
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from ai_copilot_infra.core.config import settings
from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)

# Module-level pool — initialised once at startup via lifespan
_pool: aioredis.ConnectionPool | None = None


def create_pool(redis_url: str = settings.redis_url) -> aioredis.ConnectionPool:
    """Create (but do not connect) a Redis connection pool."""
    return aioredis.ConnectionPool.from_url(
        redis_url,
        max_connections=20,
        decode_responses=True,
    )


def get_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = create_pool()
        logger.info("Redis connection pool initialised", url=settings.redis_url)
    return _pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """
    FastAPI dependency that yields an async Redis client per request.
    The client borrows a connection from the shared pool.
    """
    client: aioredis.Redis = aioredis.Redis(connection_pool=get_pool())
    try:
        yield client
    finally:
        await client.aclose()


async def close_pool() -> None:
    """Drain and close the global connection pool (call during shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection pool closed")
