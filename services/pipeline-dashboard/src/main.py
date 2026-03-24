"""Pipeline Dashboard - FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .scheduler import add_cron_job, get_scheduler, shutdown_scheduler, start_scheduler
from .sync import sync_all
from .routes.activity import router as activity_router
from .routes.api import router as api_router
from .routes.board import router as board_router
from .routes.pages import router as pages_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Pipeline Dashboard starting up")

    # Initialize database tables
    await init_db()
    logger.info("Database initialized")

    # Set up sync cron job
    add_cron_job(
        func=sync_all,
        cron_expression=settings.sync_interval_cron,
        job_id="pipeline_sync",
        name="Pipeline Data Sync",
    )
    start_scheduler()
    logger.info("Scheduler started with sync job")

    yield

    # Shutdown
    shutdown_scheduler()
    logger.info("Pipeline Dashboard shut down")


app = FastAPI(
    title="Pipeline Dashboard",
    lifespan=lifespan,
)

# Mount static files
app.mount("/pipeline/static", StaticFiles(directory="src/static"), name="static")

# Include routers
app.include_router(api_router)
app.include_router(activity_router)
app.include_router(board_router)
app.include_router(pages_router)
