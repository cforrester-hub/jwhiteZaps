"""Deputy service - handles webhooks from Deputy for timesheet events."""

import logging
from contextlib import asynccontextmanager
from datetime import date, timezone

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


async def notify_dashboard_status(
    employee_id: str,
    employee_name: str,
    clock_status: str,
) -> bool:
    """
    Notify dashboard service of employee status change for WebSocket broadcast.

    Args:
        employee_id: Deputy employee ID
        employee_name: Employee name
        clock_status: One of: clocked_in, clocked_out, on_break

    Returns:
        True if successful, False otherwise
    """
    endpoint = f"{settings.dashboard_service_url}/api/dashboard/internal/employee-status"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                endpoint,
                json={
                    "employee_id": employee_id,
                    "name": employee_name,
                    "clock_status": clock_status,
                },
                headers={"X-Internal-Key": settings.internal_api_key},
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    f"Notified dashboard of {employee_name} status: {clock_status} "
                    f"(connected clients: {result.get('connected_clients', 0)})"
                )
                return True
            else:
                logger.warning(
                    f"Failed to notify dashboard for {employee_name}: "
                    f"{response.status_code} - {response.text}"
                )
                return False

    except Exception as e:
        # Don't fail the main flow if dashboard notification fails
        logger.warning(f"Error notifying dashboard for {employee_name}: {e}")
        return False


def is_today(timesheet_date: str | None) -> bool:
    """Check if the timesheet date matches today's date."""
    if not timesheet_date:
        return False
    today_str = date.today().strftime("%Y-%m-%d")
    return timesheet_date == today_str


async def process_timesheet_event(event: ParsedTimesheetEvent) -> None:
    """
    Process a timesheet event after acquiring dedupe lock.

    - Checks if the timesheet is for today (skips past timecards)
    - Looks up the employee in user_mappings
    - Calls RingCentral to update DND status based on clock status
    """
    logger.info(
        f"Processing event: {event.action.value} for employee {event.employee_id} "
        f"(timesheet date: {event.timesheet_date})"
    )

    # Only process timesheets for today - skip past timecard approvals
    if not is_today(event.timesheet_date):
        logger.info(
            f"Skipping RingCentral update - timesheet date {event.timesheet_date} "
            f"is not today ({date.today().strftime('%Y-%m-%d')})"
        )
        if event.dedupe_key:
            await mark_dedupe_completed(event.dedupe_key)
        return

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

        # Notify dashboard service for WebSocket broadcast to desktop apps
        # Map timesheet action to clock status
        clock_status_map = {
            TimesheetAction.CLOCK_IN: "clocked_in",
            TimesheetAction.CLOCK_OUT: "clocked_out",
            TimesheetAction.BREAK_START: "on_break",
            TimesheetAction.BREAK_END: "clocked_in",  # Back to work after break
        }
        clock_status = clock_status_map.get(event.action)

        if clock_status:
            await notify_dashboard_status(
                employee_id=str(event.employee_id),
                employee_name=employee_name,
                clock_status=clock_status,
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

    today_str = date.today().strftime("%Y-%m-%d")

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
        "timesheet_date": event.timesheet_date,
        "is_today": event.timesheet_date == today_str,
        "would_update_ringcentral": event.timesheet_date == today_str,
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


@app.get("/api/deputy/employees/clock-status")
async def get_all_employees_clock_status():
    """
    Get current clock status for all mapped employees by querying Deputy API.

    Returns a list of employees with their current clock status:
    - clocked_in: Employee has an active timesheet (IsInProgress=true) with no active break
    - on_break: Employee has an active timesheet with an active break
    - clocked_out: No active timesheet found

    This endpoint is used by dashboard-service on startup to recover state.
    """
    from shared import get_all_users

    users = get_all_users()
    results = []

    # Query Deputy API for all active timesheets (IsInProgress=true)
    active_timesheets = await _query_active_timesheets()

    # Build a map of employee_id -> timesheet data
    active_by_employee: dict[str, dict] = {}
    for ts in active_timesheets:
        emp_id = str(ts.get("Employee", ""))
        if emp_id:
            active_by_employee[emp_id] = ts

    # Determine status for each mapped user
    for user in users:
        deputy_id = user.get("deputy_id")
        name = user.get("name", "Unknown")
        rc_extension_id = user.get("ringcentral_extension_id")

        if deputy_id in active_by_employee:
            timesheet = active_by_employee[deputy_id]

            # Check if on break by looking at Slots
            on_break = _is_on_active_break(timesheet.get("Slots", []))

            if on_break:
                clock_status = "on_break"
            else:
                clock_status = "clocked_in"
        else:
            clock_status = "clocked_out"

        results.append({
            "employee_id": deputy_id,
            "name": name,
            "clock_status": clock_status,
            "ringcentral_extension_id": rc_extension_id,
        })

    return {
        "employees": results,
        "active_timesheets_count": len(active_timesheets),
    }


async def _query_active_timesheets() -> list[dict]:
    """Query Deputy API for all timesheets where IsInProgress=true."""
    if not settings.deputy_base_url or not settings.deputy_access_token:
        logger.warning("Deputy API credentials not configured, cannot query timesheets")
        return []

    endpoint = f"{settings.deputy_base_url}/api/v1/resource/Timesheet/QUERY"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                endpoint,
                json={
                    "search": {
                        "s1": {"field": "IsInProgress", "data": True, "type": "eq"}
                    }
                },
                headers={
                    "Authorization": f"Bearer {settings.deputy_access_token}",
                    "Content-Type": "application/json",
                },
            )

            if response.status_code == 200:
                timesheets = response.json()
                logger.info(f"Found {len(timesheets)} active timesheets from Deputy")
                return timesheets
            else:
                logger.error(
                    f"Failed to query Deputy timesheets: {response.status_code} - {response.text}"
                )
                return []

    except Exception as e:
        logger.error(f"Error querying Deputy API: {e}")
        return []


def _is_on_active_break(slots: list) -> bool:
    """Check if there's an active break in the Slots array."""
    if not slots:
        return False

    for slot in slots:
        if not isinstance(slot, dict):
            continue

        # Check for break type
        str_type = str(slot.get("strType", "")).upper()
        if str_type != "B":
            continue

        # Check if break is in progress (has start but no end)
        start = slot.get("intUnixStart")
        end = slot.get("intUnixEnd")
        state = str(slot.get("strState", "")).lower()

        if start and not end:
            return True
        if "in progress" in state or "started" in state:
            return True

    return False
