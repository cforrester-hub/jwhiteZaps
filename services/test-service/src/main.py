"""
Test Service - A simple microservice to validate the stack.

This service demonstrates:
- FastAPI REST endpoints
- PostgreSQL database connectivity
- Redis connectivity
- Cron-style scheduled jobs
- Health checks

All endpoints are prefixed with /api/test to match Traefik routing.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from .config import get_settings
from .database import get_db, check_database_connection
from .redis_client import get_redis, check_redis_connection
from .scheduler import setup_scheduler, shutdown_scheduler

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup/shutdown events.
    - Startup: Initialize scheduler
    - Shutdown: Cleanup resources
    """
    # Startup
    logger.info(f"Starting {settings.service_name}")
    setup_scheduler()
    yield
    # Shutdown
    logger.info(f"Shutting down {settings.service_name}")
    shutdown_scheduler()


# Create FastAPI app
app = FastAPI(
    title="Test Service",
    description="A test microservice to validate the stack",
    version="1.0.0",
    docs_url="/api/test/docs",
    redoc_url="/api/test/redoc",
    openapi_url="/api/test/openapi.json",
    lifespan=lifespan,
)


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================


@app.get("/api/test/health")
async def health_check():
    """
    Basic health check endpoint.
    Returns 200 if the service is running.
    """
    return {"status": "healthy", "service": settings.service_name}


@app.get("/api/test/health/ready")
async def readiness_check():
    """
    Readiness check - verifies all dependencies are available.
    Returns 200 only if database and Redis are reachable.
    """
    db_ok = await check_database_connection()
    redis_ok = await check_redis_connection()

    if not db_ok or not redis_ok:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "not ready",
                "database": "connected" if db_ok else "disconnected",
                "redis": "connected" if redis_ok else "disconnected",
            },
        )

    return {
        "status": "ready",
        "database": "connected",
        "redis": "connected",
    }


# =============================================================================
# TEST ENDPOINTS
# =============================================================================


@app.get("/api/test/")
async def root():
    """Root endpoint with service information."""
    return {
        "service": settings.service_name,
        "message": "Test service is running!",
        "timestamp": datetime.utcnow().isoformat(),
        "docs": "/api/test/docs",
    }


@app.get("/api/test/db")
async def test_database(db: AsyncSession = Depends(get_db)):
    """
    Test database connectivity.
    Performs a simple query and returns the result.
    """
    from sqlalchemy import text

    result = await db.execute(text("SELECT version()"))
    version = result.scalar()

    return {
        "status": "connected",
        "postgres_version": version,
    }


@app.get("/api/test/redis")
async def test_redis(redis_client: aioredis.Redis = Depends(get_redis)):
    """
    Test Redis connectivity.
    Sets and gets a test value.
    """
    test_key = "test:ping"
    test_value = f"pong:{datetime.utcnow().isoformat()}"

    await redis_client.set(test_key, test_value, ex=60)
    stored_value = await redis_client.get(test_key)

    return {
        "status": "connected",
        "test_key": test_key,
        "test_value": stored_value.decode() if stored_value else None,
    }


@app.post("/api/test/webhook")
async def test_webhook(payload: dict = None):
    """
    Test webhook endpoint.
    Demonstrates how external services can trigger actions.
    In a real microservice, this would process incoming webhook data.
    """
    logger.info(f"Webhook received: {payload}")

    return {
        "status": "received",
        "payload": payload,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/api/test/external")
async def test_external_api():
    """
    Test external API call.
    Demonstrates how to call external APIs (like Zapier does).
    Uses httpbin.org as a test endpoint.
    """
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.get("https://httpbin.org/get")

    return {
        "status": "success",
        "external_api_response_status": response.status_code,
        "message": "Successfully called external API",
    }
