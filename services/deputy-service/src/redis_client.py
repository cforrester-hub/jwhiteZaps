"""Redis client for dedupe locking."""

import logging
from typing import Optional

import redis.asyncio as redis

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Global Redis connection pool
_redis_pool: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create Redis connection."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None


async def acquire_dedupe_lock(dedupe_key: str) -> bool:
    """
    Try to acquire a processing lock for a dedupe key.

    Uses Redis SET NX (set if not exists) for atomic locking.
    Only one request can acquire the lock, even if multiple
    arrive simultaneously.

    Args:
        dedupe_key: Unique key for this event (e.g., "tco_abc123")

    Returns:
        True if lock acquired (we should process), False otherwise
    """
    r = await get_redis()
    key = f"deputy:dedupe:{dedupe_key}"

    # SET key "processing" NX EX ttl
    # NX = only set if not exists
    # EX = expire after ttl seconds
    result = await r.set(
        key,
        "processing",
        nx=True,
        ex=settings.dedupe_lock_ttl,
    )

    if result:
        logger.debug(f"Acquired dedupe lock: {dedupe_key}")
        return True
    else:
        logger.debug(f"Dedupe lock already held: {dedupe_key}")
        return False


async def mark_dedupe_completed(dedupe_key: str) -> None:
    """
    Mark an event as completed and extend TTL.

    After processing completes successfully, we extend the TTL
    to prevent re-processing if the same event somehow fires again.

    Args:
        dedupe_key: Unique key for this event
    """
    r = await get_redis()
    key = f"deputy:dedupe:{dedupe_key}"

    await r.set(key, "completed", ex=settings.dedupe_completed_ttl)
    logger.debug(f"Marked dedupe completed: {dedupe_key} (TTL: {settings.dedupe_completed_ttl}s)")


async def is_dedupe_processed(dedupe_key: str) -> bool:
    """
    Check if an event was already processed.

    Args:
        dedupe_key: Unique key for this event

    Returns:
        True if already processed or being processed
    """
    r = await get_redis()
    key = f"deputy:dedupe:{dedupe_key}"
    return await r.exists(key) > 0
