"""Deputy service - handles webhooks from Deputy for timesheet events."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .redis_client import (
    acquire_dedupe_lock,
    close_redis,
    mark_dedupe_completed,
)
from .timesheet_parser import (
    DesiredDndStatus,
    ParsedTimesheetEvent,
    TimesheetAction,
    parse_timesheet_webhook,
)

# Import shared user mappings
from shared import find_by_deputy_id

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Deputy service starting up...")
    yield
    logger.info("Deputy service shutting down...")
    await close_redis()


app = FastAPI(
    title="Deputy Service",
    description="Handles Deputy webhooks for timesheet events (clock in/out, breaks)",
    version="1.0.0",
    lifespan=lifespan,
)


async def update_ringcentral_dnd(
    extension_id: str,
    dnd_status: DesiredDndStatus,
    employee_name: str,
) -> bool:
    """
    Call RingCentral service to update DND status.

    Args:
        extension_id: RingCentral extension ID
        dnd_status: Desired DND status
        employee_name: Employee name for logging

    Returns:
        True if successful, False otherwise
    """
    # Determine which endpoint to call based on desired status
    if dnd_status == DesiredDndStatus.TAKE_ALL_CALLS:
        endpoint = f"{settings.ringcentral_service_url}/api/ringcentral/extensions/{extension_id}/available"
    else:
        endpoint = f"{settings.ringcentral_service_url}/api/ringcentral/extensions/{extension_id}/unavailable"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(endpoint)

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"Updated RingCentral DND for {employee_name} (ext {extension_id}): "
                    f"{result.get('dnd_status')}"
                )
                return True
            else:
                logger.error(
                    f"Failed to update RingCentral DND for {employee_name}: "
                    f"{response.status_code} - {response.text}"
                )
                return False

    except Exception as e:
        logger.error(f"Error calling RingCentral service for {employee_name}: {e}")
        return False


async def process_timesheet_event(event: ParsedTimesheetEvent) -> None:
    """
    Process a timesheet event after acquiring dedupe lock.

    - Looks up the employee in user_mappings
    - Calls RingCentral to update DND status based on clock status
    """
    logger.info(
        f"Processing event: {event.action.value} for employee {event.employee_id}"
    )

    # Look up employee in shared user_mappings
    user = find_by_deputy_id(str(event.employee_id))

    if not user:
        logger.warning(
            f"No user mapping found for Deputy employee ID {event.employee_id}"
        )
        # Mark as completed anyway to avoid reprocessing
        if event.dedupe_key:
            await mark_dedupe_completed(event.dedupe_key)
        return

    employee_name = user.get("name", "Unknown")
    ringcentral_extension_id = user.get("ringcentral_extension_id")

    if not ringcentral_extension_id:
        logger.warning(
            f"No RingCentral extension ID for {employee_name} (Deputy ID {event.employee_id})"
        )
        if event.dedupe_key:
            await mark_dedupe_completed(event.dedupe_key)
        return

    # Update RingCentral DND status
    if event.desired_dnd_status:
        action_description = {
            TimesheetAction.CLOCK_IN: "clocked in",
            TimesheetAction.CLOCK_OUT: "clocked out",
            TimesheetAction.BREAK_START: "started break",
            TimesheetAction.BREAK_END: "ended break",
        }.get(event.action, event.action.value)

        logger.info(
            f"{employee_name} {action_description} - "
            f"setting DND to {event.desired_dnd_status.value}"
        )

        success = await update_ringcentral_dnd(
            extension_id=ringcentral_extension_id,
            dnd_status=event.desired_dnd_status,
            employee_name=employee_name,
        )

        if not success:
            logger.error(
                f"Failed to update RingCentral for {employee_name} after {action_description}"
            )

    # Mark as completed so duplicate webhooks are ignored for longer
    if event.dedupe_key:
        await mark_dedupe_completed(event.dedupe_key)


@app.get("/api/deputy/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "deputy"}


@app.get("/api/deputy/health/ready")
async def readiness_check():
    """Readiness check - verifies Redis connection."""
    try:
        from .redis_client import get_redis

        r = await get_redis()
        await r.ping()
        return {"status": "ready", "redis": "connected"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "not ready", "error": str(e)},
        )


@app.post("/api/deputy/webhook/timesheet")
async def handle_timesheet_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Handle timesheet webhook from Deputy.

    Deputy may send multiple identical webhooks simultaneously.
    We use Redis-based dedupe locking to ensure only one is processed.
    """
    try:
        payload = await request.json()
    except Exception as e:
        logger.warning(f"Failed to parse webhook payload: {e}")
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON payload"},
        )

    # Parse the webhook to determine action
    event = parse_timesheet_webhook(payload)

    # If no actionable event, just acknowledge
    if event.action == TimesheetAction.IGNORE:
        logger.debug(f"Ignoring webhook: {event.reason}")
        return {
            "status": "ignored",
            "reason": event.reason,
        }

    # If no dedupe key could be generated, still process but warn
    if not event.dedupe_key:
        logger.warning(
            f"No dedupe key for {event.action.value} event, processing anyway"
        )
        background_tasks.add_task(process_timesheet_event, event)
        return {
            "status": "accepted",
            "action": event.action.value,
            "warning": "No dedupe key generated",
        }

    # Try to acquire dedupe lock
    lock_acquired = await acquire_dedupe_lock(event.dedupe_key)

    if not lock_acquired:
        # Another request is handling this event
        logger.info(
            f"Dedupe: skipping duplicate {event.action.value} "
            f"for employee {event.employee_id} (key: {event.dedupe_key})"
        )
        return {
            "status": "duplicate",
            "action": event.action.value,
            "dedupe_key": event.dedupe_key,
        }

    # We got the lock, process in background
    logger.info(
        f"Dedupe: processing {event.action.value} "
        f"for employee {event.employee_id} (key: {event.dedupe_key})"
    )
    background_tasks.add_task(process_timesheet_event, event)

    return {
        "status": "accepted",
        "action": event.action.value,
        "employee_id": event.employee_id,
        "dedupe_key": event.dedupe_key,
    }


@app.post("/api/deputy/webhook/test")
async def test_webhook(request: Request):
    """
    Test endpoint to see how a payload would be parsed.

    Useful for debugging without actually processing the event.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid JSON: {e}"},
        )

    event = parse_timesheet_webhook(payload)

    return {
        "action": event.action.value,
        "desired_dnd_status": (
            event.desired_dnd_status.value if event.desired_dnd_status else None
        ),
        "timesheet_id": event.timesheet_id,
        "employee_id": event.employee_id,
        "event_unix": event.event_unix,
        "dedupe_key": event.dedupe_key,
        "reason": event.reason,
        "topic": event.topic,
        "debug_break": (
            {
                "start": event.debug_break.start,
                "end": event.debug_break.end,
                "state": event.debug_break.state,
                "type_name": event.debug_break.type_name,
            }
            if event.debug_break
            else None
        ),
    }
