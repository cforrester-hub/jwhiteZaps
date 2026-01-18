"""
Workflow registry and base classes.

Each workflow is a module in this package that:
1. Defines a run() async function
2. Registers itself with the workflow registry
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Dict, Any
from datetime import datetime
import uuid

from ..database import async_session, ProcessedItem, WorkflowRun

logger = logging.getLogger(__name__)


class TriggerType(Enum):
    """How a workflow is triggered."""
    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"


@dataclass
class WorkflowConfig:
    """Configuration for a workflow."""
    name: str
    description: str
    trigger_type: TriggerType
    cron_expression: Optional[str] = None  # For CRON triggers
    webhook_path: Optional[str] = None  # For WEBHOOK triggers
    enabled: bool = True
    run_func: Optional[Callable] = None


# Global registry of workflows
_workflows: Dict[str, WorkflowConfig] = {}


def register_workflow(
    name: str,
    description: str,
    trigger_type: TriggerType,
    cron_expression: Optional[str] = None,
    webhook_path: Optional[str] = None,
    enabled: bool = True,
):
    """
    Decorator to register a workflow function.

    Usage:
        @register_workflow(
            name="call_log_sync",
            description="Sync RingCentral calls to AgencyZoom",
            trigger_type=TriggerType.CRON,
            cron_expression="*/15 * * * *",
        )
        async def run():
            # workflow logic here
            pass
    """
    def decorator(func: Callable):
        config = WorkflowConfig(
            name=name,
            description=description,
            trigger_type=trigger_type,
            cron_expression=cron_expression,
            webhook_path=webhook_path,
            enabled=enabled,
            run_func=func,
        )
        _workflows[name] = config
        logger.info(f"Registered workflow: {name} ({trigger_type.value})")
        return func
    return decorator


def get_workflow(name: str) -> Optional[WorkflowConfig]:
    """Get a workflow by name."""
    return _workflows.get(name)


def get_all_workflows() -> Dict[str, WorkflowConfig]:
    """Get all registered workflows."""
    return _workflows.copy()


def get_cron_workflows() -> Dict[str, WorkflowConfig]:
    """Get all cron-triggered workflows."""
    return {
        name: config
        for name, config in _workflows.items()
        if config.trigger_type == TriggerType.CRON and config.enabled
    }


def get_webhook_workflows() -> Dict[str, WorkflowConfig]:
    """Get all webhook-triggered workflows."""
    return {
        name: config
        for name, config in _workflows.items()
        if config.trigger_type == TriggerType.WEBHOOK and config.enabled
    }


async def is_processed(item_id: str, workflow_name: str) -> bool:
    """Check if an item has already been processed by a workflow."""
    async with async_session() as session:
        result = await session.get(ProcessedItem, item_id)
        return result is not None and result.workflow_name == workflow_name


async def mark_processed(
    item_id: str,
    workflow_name: str,
    success: bool = True,
    details: Optional[str] = None,
):
    """Mark an item as processed by a workflow."""
    async with async_session() as session:
        item = ProcessedItem(
            id=f"{workflow_name}:{item_id}",
            workflow_name=workflow_name,
            success=success,
            details=details,
        )
        session.add(item)
        await session.commit()


async def start_workflow_run(workflow_name: str) -> str:
    """Record the start of a workflow run. Returns run ID."""
    run_id = str(uuid.uuid4())
    async with async_session() as session:
        run = WorkflowRun(
            id=run_id,
            workflow_name=workflow_name,
            status="running",
        )
        session.add(run)
        await session.commit()
    return run_id


async def complete_workflow_run(
    run_id: str,
    success: bool,
    items_processed: int = 0,
    error_message: Optional[str] = None,
):
    """Record the completion of a workflow run."""
    async with async_session() as session:
        run = await session.get(WorkflowRun, run_id)
        if run:
            run.completed_at = datetime.utcnow()
            run.status = "success" if success else "failed"
            run.items_processed = str(items_processed)
            run.error_message = error_message
            await session.commit()


async def run_workflow(name: str, **kwargs) -> Dict[str, Any]:
    """
    Execute a workflow by name with tracking.

    Returns a dict with run results.
    """
    config = get_workflow(name)
    if not config:
        raise ValueError(f"Unknown workflow: {name}")

    if not config.enabled:
        logger.warning(f"Workflow {name} is disabled")
        return {"status": "skipped", "reason": "disabled"}

    run_id = await start_workflow_run(name)
    logger.info(f"Starting workflow: {name} (run_id={run_id})")

    try:
        result = await config.run_func(**kwargs)
        items_processed = result.get("items_processed", 0) if isinstance(result, dict) else 0
        await complete_workflow_run(run_id, success=True, items_processed=items_processed)
        logger.info(f"Workflow {name} completed successfully")
        return {"status": "success", "run_id": run_id, "result": result}
    except Exception as e:
        logger.error(f"Workflow {name} failed: {e}")
        await complete_workflow_run(run_id, success=False, error_message=str(e))
        return {"status": "failed", "run_id": run_id, "error": str(e)}
