"""AZ Analyst Service - FastAPI application."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .routes.analysis import router as analysis_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("AZ Analyst Service starting up")
    yield
    logger.info("AZ Analyst Service shut down")


app = FastAPI(
    title="AZ Analyst Service",
    lifespan=lifespan,
)

app.include_router(analysis_router)
