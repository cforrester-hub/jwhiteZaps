"""
Workflow Service - Automation engine for Zapier replacement.

This service handles:
- Cron-scheduled workflows (via APScheduler)
- Webhook-triggered workflows (via FastAPI endpoints)
- Manual workflow execution (via API)
"""

import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings
from .database import init_db
from .http_client import close_client
from .logging_config import setup_logging, get_logger
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
from .workflows import outgoing_call  # noqa: F401
from .workflows import incoming_call  # noqa: F401

# Configure structured JSON logging
setup_logging()
logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests and responses."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Log request
        logger.info(
            "request_started",
            extra={
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params) if request.query_params else None,
                "client_ip": request.client.host if request.client else None,
            },
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # Log response
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )

            return response

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                "request_failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(e),
                },
            )
            raise


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
            # Create a proper async wrapper function for the scheduler
            # APScheduler needs an actual async function, not a lambda returning a coroutine
            async def workflow_runner(workflow_name=name):
                await run_workflow(workflow_name)

            add_cron_job(
                func=workflow_runner,
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

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

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


@app.get("/api/workflows/processed/{workflow_name}")
async def get_processed_items(workflow_name: str, limit: int = 100):
    """
    Get processed items for a workflow.
    Useful for debugging and auditing which items have been processed.
    """
    from sqlalchemy import select
    from .database import async_session, ProcessedItem

    async with async_session() as session:
        stmt = (
            select(ProcessedItem)
            .where(ProcessedItem.workflow_name == workflow_name)
            .order_by(ProcessedItem.processed_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        items = result.scalars().all()

    return {
        "workflow_name": workflow_name,
        "count": len(items),
        "items": [
            {
                "id": item.id,
                "processed_at": item.processed_at.isoformat() if item.processed_at else None,
                "success": item.success,
                "details": item.details,
            }
            for item in items
        ],
    }


@app.delete("/api/workflows/processed/{workflow_name}")
async def clear_processed_items(workflow_name: str):
    """
    Clear all processed items for a workflow.
    This allows reprocessing of all items on the next run.
    USE WITH CAUTION - this will cause duplicate processing if items were already
    successfully synced to external systems.
    """
    from sqlalchemy import delete
    from .database import async_session, ProcessedItem

    async with async_session() as session:
        stmt = delete(ProcessedItem).where(ProcessedItem.workflow_name == workflow_name)
        result = await session.execute(stmt)
        await session.commit()
        deleted_count = result.rowcount

    logger.warning(f"Cleared {deleted_count} processed items for workflow: {workflow_name}")
    return {"status": "cleared", "workflow_name": workflow_name, "items_deleted": deleted_count}


@app.delete("/api/workflows/processed/{workflow_name}/{item_id}")
async def clear_single_processed_item(workflow_name: str, item_id: str):
    """
    Clear a single processed item for a workflow.
    This allows reprocessing of a specific item on the next run.
    """
    from .database import async_session, ProcessedItem

    composite_id = f"{workflow_name}:{item_id}"
    async with async_session() as session:
        item = await session.get(ProcessedItem, composite_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Processed item not found: {item_id}")
        await session.delete(item)
        await session.commit()

    logger.info(f"Cleared processed item {item_id} for workflow: {workflow_name}")
    return {"status": "cleared", "workflow_name": workflow_name, "item_id": item_id}
