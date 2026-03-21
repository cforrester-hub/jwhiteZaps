"""AZ Analyst Service - FastAPI application."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

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

OPENAPI_PATH = Path(__file__).resolve().parent.parent / "openapi.json"


@app.get("/api/analysis/openapi.json", include_in_schema=False)
async def serve_openapi():
    """Serve the hand-maintained OpenAPI spec for ChatGPT import."""
    return FileResponse(OPENAPI_PATH, media_type="application/json")
