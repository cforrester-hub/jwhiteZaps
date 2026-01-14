"""
Redis client for caching and message queue operations.
"""

import redis.asyncio as redis
from .config import get_settings

settings = get_settings()

# Create Redis connection pool
redis_pool = redis.ConnectionPool.from_url(settings.redis_url)


async def get_redis() -> redis.Redis:
    """
    Get a Redis client instance.
    Usage in FastAPI endpoint:
        @app.get("/")
        async def endpoint(redis_client: redis.Redis = Depends(get_redis)):
            ...
    """
    return redis.Redis(connection_pool=redis_pool)


async def check_redis_connection() -> bool:
    """Check if Redis is reachable."""
    try:
        client = await get_redis()
        await client.ping()
        return True
    except Exception:
        return False
