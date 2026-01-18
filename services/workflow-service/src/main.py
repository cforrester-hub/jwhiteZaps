"""
Workflow Service - Automation engine for Zapier replacement.

This service handles:
- Cron-scheduled workflows (via APScheduler)
- Webhook-triggered workflows (via FastAPI endpoints)
- Manual workflow execution (via API)
"""

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .database import init_db
from .http_client import close_client
from .scheduler import (
    start_scheduler,
    shutdown_scheduler,
    add_cron_job,
    list_jobs,
)
from .webhooks import router as webhook_router
from .workflows import (
    get_all_workflows,
    get_cron_workflows,
    get_workflow,
    run_workflow,
)

# Import workflow modules to register them
from .workflows import example_workflow  # noqa: F401
# Add your workflows here:
# from .workflows import call_log_sync  # noqa: F401

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    # Startup
    logger.info("Starting workflow service...")

    # Initialize database tables
    await init_db()
    logger.info("Database initialized")

    # Register cron workflows with scheduler
    for name, config in get_cron_workflows().items():
        if config.cron_expression:
            add_cron_job(
                func=lambda n=name: run_workflow(n),
                cron_expression=config.cron_expression,
                job_id=name,
                name=config.description,
            )

    # Start the scheduler
    start_scheduler()

    yield

    # Shutdown
    logger.info("Shutting down workflow service...")
    shutdown_scheduler()
    await close_client()


app = FastAPI(
    title="Workflow Service",
    description="Automation engine for running scheduled and webhook-triggered workflows",
    version="1.0.0",
    docs_url="/api/workflows/docs",
    redoc_url="/api/workflows/redoc",
    openapi_url="/api/workflows/openapi.json",
    lifespan=lifespan,
)

# Include webhook routes
app.include_router(webhook_router, prefix="/api/workflows")


# Response models
class HealthResponse(BaseModel):
    status: str
    service: str


class WorkflowInfo(BaseModel):
    name: str
    description: str
    trigger_type: str
    cron_expression: Optional[str] = None
    webhook_path: Optional[str] = None
    enabled: bool


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowInfo]


class ScheduledJobInfo(BaseModel):
    id: str
    name: str
    next_run: Optional[str] = None


class SchedulerStatusResponse(BaseModel):
    jobs: list[ScheduledJobInfo]


class WorkflowRunRequest(BaseModel):
    workflow_name: str


class WorkflowRunResponse(BaseModel):
    status: str
    run_id: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


# Endpoints
@app.get("/api/workflows/health", response_model=HealthResponse)
async def health_check():
    """Basic health check endpoint."""
    return HealthResponse(status="healthy", service="workflow-service")


@app.get("/api/workflows/list", response_model=WorkflowListResponse)
async def list_workflows():
    """List all registered workflows."""
    workflows = []
    for name, config in get_all_workflows().items():
        workflows.append(
            WorkflowInfo(
                name=config.name,
                description=config.description,
                trigger_type=config.trigger_type.value,
                cron_expression=config.cron_expression,
                webhook_path=config.webhook_path,
                enabled=config.enabled,
            )
        )
    return WorkflowListResponse(workflows=workflows)


@app.get("/api/workflows/scheduler", response_model=SchedulerStatusResponse)
async def scheduler_status():
    """Get the status of scheduled jobs."""
    jobs = list_jobs()
    return SchedulerStatusResponse(
        jobs=[ScheduledJobInfo(**job) for job in jobs]
    )


@app.post("/api/workflows/run", response_model=WorkflowRunResponse)
async def run_workflow_manually(request: WorkflowRunRequest):
    """Manually trigger a workflow."""
    config = get_workflow(request.workflow_name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {request.workflow_name}")

    result = await run_workflow(request.workflow_name)
    return WorkflowRunResponse(**result)


@app.post("/api/workflows/run/{workflow_name}", response_model=WorkflowRunResponse)
async def run_workflow_by_name(workflow_name: str):
    """Manually trigger a workflow by name (URL path)."""
    config = get_workflow(workflow_name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_name}")

    result = await run_workflow(workflow_name)
    return WorkflowRunResponse(**result)
