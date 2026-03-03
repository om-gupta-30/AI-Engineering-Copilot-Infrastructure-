"""
RedisService — async Redis operations for the application layer.

Responsibilities:
  - Provide typed, logged wrappers over raw redis-py commands
  - Surface cache hit/miss, key writes, and rate-counter events as
    structured Loguru log entries
  - Own no business logic; callers decide what keys mean and when to call

Connection management:
  RedisService borrows a client from the shared pool in infra/redis_client.py.
  Pass a custom redis.asyncio.Redis instance to the constructor for testing
  (e.g. fakeredis.aioredis.FakeRedis).

Usage:
    svc = RedisService()
    await svc.set("session:abc", json.dumps(payload), ttl=3600)
    value = await svc.get("session:abc")
    count = await svc.increment("rate:user:42", ttl=60)
"""

from __future__ import annotations

import redis.asyncio as aioredis

from ai_copilot_infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── Domain exceptions ─────────────────────────────────────────────────────────


class RedisServiceError(Exception):
    """Base exception for all RedisService errors."""


class RedisConnectionError(RedisServiceError):
    """Raised when the Redis server is unreachable."""


class RedisOperationError(RedisServiceError):
    """Raised when a Redis command fails for a non-connection reason."""


# ── Service ───────────────────────────────────────────────────────────────────


class RedisService:
    """
    Pure infrastructure wrapper around redis.asyncio.

    All methods are async, fully typed, and emit one structured log event
    per operation. No TTL defaults are baked into Redis itself — every write
    carries an explicit expiry so the keyspace stays bounded.
    """

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            from ai_copilot_infra.infra.redis_client import get_pool

            self._client = aioredis.Redis(
                connection_pool=get_pool(),
                decode_responses=True,
            )

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get(self, key: str) -> str | None:
        """
        Fetch a string value by key.

        Returns:
            The stored string, or None on a cache miss.
        """
        try:
            value: str | None = await self._client.get(key)
        except aioredis.RedisError as exc:
            self._raise_operation_error("get", key, exc)

        if value is None:
            logger.debug("cache_miss", key=key)
        else:
            logger.debug("cache_hit", key=key, value_length=len(value))

        return value

    # ── Write ─────────────────────────────────────────────────────────────────

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        """
        Store a string value with an explicit TTL (seconds).

        Args:
            key:   Redis key.
            value: String payload to store.
            ttl:   Expiry in seconds. Defaults to 3600 (1 hour).
        """
        try:
            await self._client.set(key, value, ex=ttl)
        except aioredis.RedisError as exc:
            self._raise_operation_error("set", key, exc)

        logger.debug(
            "cache_key_set",
            key=key,
            value_length=len(value),
            ttl_seconds=ttl,
        )

    # ── Existence check ───────────────────────────────────────────────────────

    async def exists(self, key: str) -> bool:
        """
        Return True if the key is present in Redis, False otherwise.

        Note: uses EXISTS which returns an integer count; we check > 0
        so the method works correctly even if called with a single key.
        """
        try:
            count: int = await self._client.exists(key)
        except aioredis.RedisError as exc:
            self._raise_operation_error("exists", key, exc)

        present = count > 0
        logger.debug("cache_exists_check", key=key, exists=present)
        return present

    # ── Rate counter ──────────────────────────────────────────────────────────

    async def increment(self, key: str, ttl: int = 60) -> int:
        """
        Atomically increment a counter key and set its TTL on first creation.

        Uses a Redis pipeline to make INCR + EXPIRE atomic from the caller's
        perspective. The EXPIRE is only applied when the key is new (i.e.
        its value is 1 after INCR), preserving the original window for
        subsequent increments within the same TTL period.

        Args:
            key: Redis key for the counter (e.g. "rate:user:42").
            ttl: Window duration in seconds. Defaults to 60.

        Returns:
            Current counter value after the increment.
        """
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                await pipe.incr(key)
                await pipe.expire(key, ttl)
                results = await pipe.execute()
            count: int = results[0]
        except aioredis.RedisError as exc:
            self._raise_operation_error("increment", key, exc)

        logger.debug(
            "rate_counter_incremented",
            key=key,
            count=count,
            ttl_seconds=ttl,
        )
        return count

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _raise_operation_error(operation: str, key: str, exc: Exception) -> None:
        """Log and re-raise a Redis error as a typed domain exception."""
        is_conn_error = isinstance(exc, aioredis.ConnectionError)
        event = "redis_connection_error" if is_conn_error else "redis_operation_error"

        logger.error(
            event,
            operation=operation,
            key=key,
            error=str(exc),
            exc_info=True,
        )

        if is_conn_error:
            raise RedisConnectionError(
                f"Redis connection failed during '{operation}' on key '{key}'."
            ) from exc

        raise RedisOperationError(f"Redis '{operation}' failed on key '{key}': {exc}") from exc
