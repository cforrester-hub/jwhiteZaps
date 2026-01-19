"""
Dashboard Service - Service Health Monitor

A simple dashboard that displays the health status of all microservices
and workflow information. Also provides employee clock status via WebSocket
for the Windows desktop app.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import uuid4

import httpx
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from .config import get_settings
from .employee_status import (
    ClockStatus,
    EmployeeStatus,
    status_manager,
)

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def initialize_employee_statuses():
    """Initialize employee statuses by querying Deputy for current timesheet status."""
    try:
        # Query deputy-service for current clock status of all employees
        await recover_statuses_from_deputy()

    except Exception as e:
        logger.error(f"Failed to initialize employee statuses: {e}")
        # Fall back to initializing with unknown status
        await _initialize_employees_unknown()


async def _initialize_employees_unknown():
    """Initialize all employees with unknown status (fallback)."""
    try:
        from shared import get_all_users

        users = get_all_users()
        logger.info(f"Initializing {len(users)} employees with unknown status (fallback)")

        for user in users:
            deputy_id = user.get("deputy_id")
            name = user.get("name", "Unknown")
            rc_extension_id = user.get("ringcentral_extension_id")

            await status_manager.initialize_employee(
                employee_id=deputy_id,
                name=name,
                ringcentral_extension_id=rc_extension_id,
                clock_status=ClockStatus.UNKNOWN,
            )
    except Exception as e:
        logger.error(f"Failed to initialize employees with unknown status: {e}")


async def recover_statuses_from_deputy():
    """Query Deputy via deputy-service to get current clock status for all employees."""
    endpoint = f"{settings.deputy_service_url}/api/deputy/employees/clock-status"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(endpoint)

            if response.status_code == 200:
                data = response.json()
                employees = data.get("employees", [])
                active_count = data.get("active_timesheets_count", 0)

                logger.info(
                    f"Recovered status from Deputy: {len(employees)} employees, "
                    f"{active_count} active timesheets"
                )

                for emp in employees:
                    employee_id = emp.get("employee_id")
                    name = emp.get("name", "Unknown")
                    status_str = emp.get("clock_status", "unknown")
                    rc_extension_id = emp.get("ringcentral_extension_id")

                    # Map string to ClockStatus enum
                    status_map = {
                        "clocked_in": ClockStatus.CLOCKED_IN,
                        "clocked_out": ClockStatus.CLOCKED_OUT,
                        "on_break": ClockStatus.ON_BREAK,
                    }
                    clock_status = status_map.get(status_str, ClockStatus.UNKNOWN)

                    await status_manager.initialize_employee(
                        employee_id=employee_id,
                        name=name,
                        ringcentral_extension_id=rc_extension_id,
                        clock_status=clock_status,
                    )
                    logger.info(f"Initialized {name}: {clock_status.value}")

            else:
                logger.error(
                    f"Failed to query deputy-service: {response.status_code} - {response.text}"
                )
                await _initialize_employees_unknown()

    except Exception as e:
        logger.error(f"Error querying deputy-service for status recovery: {e}")
        await _initialize_employees_unknown()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Dashboard service starting up...")

    # Set up API key for desktop app authentication
    if settings.employee_status_api_key:
        status_manager.add_api_key(settings.employee_status_api_key)
        logger.info("Using configured employee status API key")
    else:
        # Generate one and log it for the first run
        generated_key = status_manager.generate_api_key()
        logger.warning(f"Generated employee status API key: {generated_key}")
        logger.warning("Set EMPLOYEE_STATUS_API_KEY env var to use a persistent key")

    # Initialize employee statuses from shared mappings
    await initialize_employee_statuses()

    yield
    logger.info("Dashboard service shutting down...")


app = FastAPI(
    title="Dashboard Service",
    description="Service health monitoring dashboard with employee status WebSocket",
    version="1.0.0",
    docs_url="/api/dashboard/docs",
    redoc_url="/api/dashboard/redoc",
    openapi_url="/api/dashboard/openapi.json",
    lifespan=lifespan,
)


class ServiceStatus(BaseModel):
    """Status of a single service."""
    name: str
    url: str
    status: str  # "healthy", "unhealthy", "unknown"
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: str


class WorkflowInfo(BaseModel):
    """Information about a workflow."""
    name: str
    description: str
    trigger_type: str
    cron_expression: Optional[str] = None
    enabled: bool


class ScheduledJobInfo(BaseModel):
    """Information about a scheduled job."""
    id: str
    name: str
    next_run: Optional[str] = None


class DashboardData(BaseModel):
    """Complete dashboard data."""
    services: list[ServiceStatus]
    workflows: list[WorkflowInfo]
    scheduled_jobs: list[ScheduledJobInfo]
    checked_at: str
    healthy_count: int
    total_count: int


async def check_service_health(name: str, url: str) -> ServiceStatus:
    """Check the health of a single service."""
    start_time = datetime.utcnow()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url)
            response_time = (datetime.utcnow() - start_time).total_seconds() * 1000

            if response.status_code == 200:
                return ServiceStatus(
                    name=name,
                    url=url,
                    status="healthy",
                    response_time_ms=round(response_time, 2),
                    checked_at=datetime.utcnow().isoformat(),
                )
            else:
                return ServiceStatus(
                    name=name,
                    url=url,
                    status="unhealthy",
                    response_time_ms=round(response_time, 2),
                    error=f"HTTP {response.status_code}",
                    checked_at=datetime.utcnow().isoformat(),
                )
    except httpx.TimeoutException:
        return ServiceStatus(
            name=name,
            url=url,
            status="unhealthy",
            error="Timeout",
            checked_at=datetime.utcnow().isoformat(),
        )
    except Exception as e:
        return ServiceStatus(
            name=name,
            url=url,
            status="unknown",
            error=str(e),
            checked_at=datetime.utcnow().isoformat(),
        )


async def get_workflow_info() -> tuple[list[WorkflowInfo], list[ScheduledJobInfo]]:
    """Fetch workflow and scheduler information from workflow-service."""
    workflows = []
    scheduled_jobs = []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Get workflows
            workflows_response = await client.get(
                "http://workflow-service:8000/api/workflows/list"
            )
            if workflows_response.status_code == 200:
                data = workflows_response.json()
                for wf in data.get("workflows", []):
                    workflows.append(WorkflowInfo(
                        name=wf.get("name", ""),
                        description=wf.get("description", ""),
                        trigger_type=wf.get("trigger_type", ""),
                        cron_expression=wf.get("cron_expression"),
                        enabled=wf.get("enabled", False),
                    ))

            # Get scheduler status
            scheduler_response = await client.get(
                "http://workflow-service:8000/api/workflows/scheduler"
            )
            if scheduler_response.status_code == 200:
                data = scheduler_response.json()
                for job in data.get("jobs", []):
                    scheduled_jobs.append(ScheduledJobInfo(
                        id=job.get("id", ""),
                        name=job.get("name", ""),
                        next_run=job.get("next_run"),
                    ))

    except Exception as e:
        logger.error(f"Failed to fetch workflow info: {e}")

    return workflows, scheduled_jobs


async def get_all_service_statuses() -> DashboardData:
    """Check all services concurrently and fetch workflow info."""
    # Check service health
    health_tasks = [
        check_service_health(name, url)
        for name, url in settings.services.items()
    ]

    # Fetch workflow info
    statuses = await asyncio.gather(*health_tasks)
    workflows, scheduled_jobs = await get_workflow_info()

    healthy_count = sum(1 for s in statuses if s.status == "healthy")

    return DashboardData(
        services=list(statuses),
        workflows=workflows,
        scheduled_jobs=scheduled_jobs,
        checked_at=datetime.utcnow().isoformat(),
        healthy_count=healthy_count,
        total_count=len(statuses),
    )


def generate_dashboard_html(data: DashboardData) -> str:
    """Generate the dashboard HTML."""
    # Format timestamp
    checked_at = datetime.fromisoformat(data.checked_at).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Generate service cards
    service_cards = []
    for service in data.services:
        details = []
        if service.response_time_ms is not None:
            details.append(f'<p class="response-time">Response: {service.response_time_ms}ms</p>')
        if service.error:
            details.append(f'<p class="error-message">Error: {service.error}</p>')

        details_html = "\n".join(details) if details else "<p>No additional info</p>"

        card = f'''
        <div class="service-card">
            <div class="service-header">
                <span class="service-name">{service.name}</span>
                <span class="status-badge {service.status}">{service.status}</span>
            </div>
            <div class="service-details">
                {details_html}
            </div>
        </div>
        '''
        service_cards.append(card)

    service_cards_html = "\n".join(service_cards)

    # Generate workflow rows
    workflow_rows = []
    for wf in data.workflows:
        status_class = "enabled" if wf.enabled else "disabled"
        status_text = "Enabled" if wf.enabled else "Disabled"
        cron = wf.cron_expression or "-"

        # Find next run time for this workflow
        next_run = "-"
        for job in data.scheduled_jobs:
            if job.id == wf.name:
                if job.next_run:
                    try:
                        next_dt = datetime.fromisoformat(job.next_run.replace("Z", "+00:00"))
                        next_run = next_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        next_run = job.next_run
                break

        row = f'''
        <tr>
            <td class="workflow-name">{wf.name}</td>
            <td>{wf.description}</td>
            <td><span class="trigger-badge">{wf.trigger_type}</span></td>
            <td class="cron">{cron}</td>
            <td class="next-run">{next_run}</td>
            <td><span class="status-badge {status_class}">{status_text}</span></td>
            <td>
                <button class="run-btn" onclick="runWorkflow('{wf.name}')">Run Now</button>
            </td>
        </tr>
        '''
        workflow_rows.append(row)

    workflow_rows_html = "\n".join(workflow_rows) if workflow_rows else '<tr><td colspan="7">No workflows registered</td></tr>'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="30">
    <title>Service Dashboard - JWhite Zaps</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            color: #e4e4e4;
            padding: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        header {{
            text-align: center;
            margin-bottom: 30px;
        }}

        h1 {{
            font-size: 2rem;
            margin-bottom: 10px;
            color: #fff;
        }}

        h2 {{
            font-size: 1.5rem;
            margin: 30px 0 20px 0;
            color: #fff;
            border-bottom: 1px solid rgba(255,255,255,0.2);
            padding-bottom: 10px;
        }}

        .summary {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-bottom: 30px;
        }}

        .summary-card {{
            background: rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 20px 40px;
            text-align: center;
            backdrop-filter: blur(10px);
        }}

        .summary-card.healthy {{
            border: 2px solid #4ade80;
        }}

        .summary-card.total {{
            border: 2px solid #60a5fa;
        }}

        .summary-number {{
            font-size: 3rem;
            font-weight: bold;
        }}

        .summary-card.healthy .summary-number {{
            color: #4ade80;
        }}

        .summary-card.total .summary-number {{
            color: #60a5fa;
        }}

        .summary-label {{
            font-size: 0.9rem;
            color: #a0a0a0;
            margin-top: 5px;
        }}

        .services-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }}

        .service-card {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .service-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3);
        }}

        .service-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .service-name {{
            font-weight: 600;
            font-size: 1.1rem;
        }}

        .status-badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .status-badge.healthy, .status-badge.enabled {{
            background: rgba(74, 222, 128, 0.2);
            color: #4ade80;
        }}

        .status-badge.unhealthy, .status-badge.disabled {{
            background: rgba(248, 113, 113, 0.2);
            color: #f87171;
        }}

        .status-badge.unknown {{
            background: rgba(251, 191, 36, 0.2);
            color: #fbbf24;
        }}

        .trigger-badge {{
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            background: rgba(96, 165, 250, 0.2);
            color: #60a5fa;
        }}

        .service-details {{
            font-size: 0.85rem;
            color: #a0a0a0;
        }}

        .service-details p {{
            margin: 5px 0;
        }}

        .response-time {{
            color: #60a5fa;
        }}

        .error-message {{
            color: #f87171;
            font-style: italic;
        }}

        /* Workflow table */
        .workflow-table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            overflow: hidden;
        }}

        .workflow-table th, .workflow-table td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}

        .workflow-table th {{
            background: rgba(255, 255, 255, 0.1);
            font-weight: 600;
            color: #fff;
        }}

        .workflow-table tr:hover {{
            background: rgba(255, 255, 255, 0.05);
        }}

        .workflow-name {{
            font-weight: 600;
            color: #60a5fa;
        }}

        .cron {{
            font-family: monospace;
            color: #a0a0a0;
        }}

        .next-run {{
            color: #4ade80;
            font-size: 0.9rem;
        }}

        .run-btn {{
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            background: #60a5fa;
            color: #fff;
            font-size: 0.85rem;
            cursor: pointer;
            transition: background 0.2s;
        }}

        .run-btn:hover {{
            background: #3b82f6;
        }}

        .run-btn:disabled {{
            background: #666;
            cursor: not-allowed;
        }}

        /* Result toast */
        .toast {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            padding: 16px 24px;
            border-radius: 8px;
            color: #fff;
            font-weight: 500;
            z-index: 1000;
            display: none;
        }}

        .toast.success {{
            background: #4ade80;
        }}

        .toast.error {{
            background: #f87171;
        }}

        .toast.show {{
            display: block;
            animation: slideIn 0.3s ease;
        }}

        @keyframes slideIn {{
            from {{
                transform: translateX(100%);
                opacity: 0;
            }}
            to {{
                transform: translateX(0);
                opacity: 1;
            }}
        }}

        footer {{
            text-align: center;
            margin-top: 40px;
            color: #666;
            font-size: 0.85rem;
        }}

        .refresh-note {{
            margin-top: 10px;
            font-size: 0.8rem;
            color: #666;
        }}

        /* Desktop app download section */
        .download-section {{
            margin-top: 30px;
            padding: 20px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}

        .download-section h2 {{
            margin-top: 0;
            border-bottom: none;
            padding-bottom: 0;
        }}

        .download-btn {{
            display: inline-flex;
            align-items: center;
            gap: 10px;
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            background: linear-gradient(135deg, #4ade80 0%, #22c55e 100%);
            color: #fff;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            text-decoration: none;
        }}

        .download-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(74, 222, 128, 0.4);
        }}

        .download-info {{
            margin-top: 15px;
            font-size: 0.9rem;
            color: #a0a0a0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>JWhite Zaps - Service Dashboard</h1>
            <p>Last checked: {checked_at}</p>
        </header>

        <div class="summary">
            <div class="summary-card healthy">
                <div class="summary-number">{data.healthy_count}</div>
                <div class="summary-label">Healthy</div>
            </div>
            <div class="summary-card total">
                <div class="summary-number">{data.total_count}</div>
                <div class="summary-label">Total Services</div>
            </div>
        </div>

        <h2>Services</h2>
        <div class="services-grid">
            {service_cards_html}
        </div>

        <h2>Workflows</h2>
        <table class="workflow-table">
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Description</th>
                    <th>Trigger</th>
                    <th>Schedule</th>
                    <th>Next Run</th>
                    <th>Status</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                {workflow_rows_html}
            </tbody>
        </table>

        <div class="download-section">
            <h2>Desktop Status Monitor</h2>
            <p style="margin-bottom: 15px; color: #e4e4e4;">
                Download the Windows desktop app to see employee clock status in real-time.
            </p>
            <a href="/api/dashboard/download/desktop-app" class="download-btn">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7,10 12,15 17,10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Download for Windows
            </a>
            <div class="download-info">
                <p>Requires Windows 10 or later. The app displays as a small floating window and runs in the system tray.</p>
            </div>
        </div>

        <footer>
            <p class="refresh-note">Auto-refreshes every 30 seconds</p>
        </footer>
    </div>

    <div id="toast" class="toast"></div>

    <script>
        async function runWorkflow(name) {{
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = 'Running...';

            try {{
                const response = await fetch('/api/workflows/run/' + name, {{
                    method: 'POST'
                }});
                const result = await response.json();

                if (result.status === 'success') {{
                    showToast('Workflow completed successfully!', 'success');
                }} else {{
                    showToast('Workflow failed: ' + (result.error || 'Unknown error'), 'error');
                }}
            }} catch (err) {{
                showToast('Request failed: ' + err.message, 'error');
            }} finally {{
                btn.disabled = false;
                btn.textContent = 'Run Now';
            }}
        }}

        function showToast(message, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = message;
            toast.className = 'toast ' + type + ' show';

            setTimeout(() => {{
                toast.classList.remove('show');
            }}, 5000);
        }}
    </script>
</body>
</html>'''

    return html


@app.get("/api/dashboard/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "dashboard-service"}


@app.get("/api/dashboard/status", response_model=DashboardData)
async def get_status():
    """Get raw status data as JSON."""
    return await get_all_service_statuses()


@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Render the dashboard HTML page."""
    data = await get_all_service_statuses()
    html = generate_dashboard_html(data)
    return HTMLResponse(content=html)


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect root to dashboard."""
    return await dashboard()


# =============================================================================
# EMPLOYEE STATUS API - For Windows Desktop App
# =============================================================================


class StatusUpdateRequest(BaseModel):
    """Request body for status update from deputy-service."""

    employee_id: str
    name: str
    clock_status: str  # clocked_in, clocked_out, on_break


class EmployeeStatusResponse(BaseModel):
    """Response containing employee statuses."""

    employees: list[EmployeeStatus]
    connected_clients: int


@app.websocket("/api/dashboard/employee-status/ws")
async def employee_status_websocket(
    websocket: WebSocket,
    api_key: str = Query(..., description="API key for authentication"),
):
    """
    WebSocket endpoint for real-time employee status updates.

    Connect with: ws://host/api/dashboard/employee-status/ws?api_key=YOUR_KEY

    On connection, you'll receive all current statuses.
    Updates are pushed automatically when status changes.
    """
    # Validate API key
    if not status_manager.validate_api_key(api_key):
        await websocket.close(code=4001, reason="Invalid API key")
        return

    await websocket.accept()

    # Generate client ID and register
    client_id = f"client_{uuid4().hex[:8]}"
    await status_manager.register_connection(websocket, client_id)

    # Send all current statuses immediately
    await status_manager.send_all_statuses(websocket)

    try:
        # Keep connection alive, handle incoming messages (like ping)
        while True:
            data = await websocket.receive_text()
            # Could handle client commands here if needed (e.g., ping/pong)
            if data == "ping":
                await websocket.send_text('{"type": "pong"}')

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error for {client_id}: {e}")
    finally:
        await status_manager.unregister_connection(websocket)


@app.get("/api/dashboard/employee-status")
async def get_employee_statuses(
    x_api_key: str = Header(None, alias="X-API-Key"),
    api_key: str = Query(None),
) -> EmployeeStatusResponse:
    """
    Get all employee clock statuses (REST endpoint).

    Authenticate via X-API-Key header or api_key query parameter.
    Use this for initial load or if WebSocket is unavailable.
    """
    # Check either header or query param
    key = x_api_key or api_key
    if not key or not status_manager.validate_api_key(key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    statuses = await status_manager.get_all_statuses()
    return EmployeeStatusResponse(
        employees=statuses,
        connected_clients=status_manager.connection_count,
    )


@app.get("/api/dashboard/employee-status/{employee_id}")
async def get_employee_status(
    employee_id: str,
    x_api_key: str = Header(None, alias="X-API-Key"),
    api_key: str = Query(None),
) -> EmployeeStatus:
    """Get status for a specific employee."""
    key = x_api_key or api_key
    if not key or not status_manager.validate_api_key(key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    status = await status_manager.get_status(employee_id)
    if not status:
        raise HTTPException(status_code=404, detail="Employee not found")
    return status


# =============================================================================
# INTERNAL API - For Deputy Service to Publish Updates
# =============================================================================


@app.post("/api/dashboard/internal/employee-status")
async def update_employee_status(
    request: StatusUpdateRequest,
    x_internal_key: str = Header(..., alias="X-Internal-Key"),
):
    """
    Internal endpoint for deputy-service to publish status updates.

    This is called when an employee clocks in/out or starts/ends a break.
    The update is broadcast to all connected WebSocket clients.
    """
    if x_internal_key != settings.internal_api_key:
        raise HTTPException(status_code=401, detail="Invalid internal key")

    # Map string to ClockStatus enum
    try:
        clock_status = ClockStatus(request.clock_status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid clock_status. Must be one of: {[s.value for s in ClockStatus]}",
        )

    # Get RingCentral extension ID from shared mappings if available
    ringcentral_extension_id = None
    try:
        from shared import find_by_deputy_id

        user = find_by_deputy_id(request.employee_id)
        if user:
            ringcentral_extension_id = user.get("ringcentral_extension_id")
    except Exception:
        pass

    await status_manager.update_status(
        employee_id=request.employee_id,
        name=request.name,
        clock_status=clock_status,
        ringcentral_extension_id=ringcentral_extension_id,
    )

    return {
        "status": "updated",
        "employee_id": request.employee_id,
        "clock_status": clock_status.value,
        "connected_clients": status_manager.connection_count,
    }


@app.get("/api/dashboard/employee-status/info")
async def employee_status_info():
    """
    Public info endpoint showing how to connect to the employee status API.

    No authentication required - just provides connection information.
    """
    return {
        "websocket_url": "/api/dashboard/employee-status/ws?api_key=YOUR_API_KEY",
        "rest_url": "/api/dashboard/employee-status",
        "authentication": {
            "websocket": "Pass api_key as query parameter",
            "rest": "Pass X-API-Key header or api_key query parameter",
        },
        "connected_clients": status_manager.connection_count,
        "message_types": {
            "all_statuses": "Sent on connection with all current employee statuses",
            "status_update": "Sent when an employee's status changes",
        },
    }


# =============================================================================
# DESKTOP APP DOWNLOAD
# =============================================================================

DOWNLOADS_DIR = Path("/app/downloads")


@app.get("/api/dashboard/download/desktop-app")
async def download_desktop_app():
    """
    Download the Windows desktop application for employee status monitoring.

    Returns the latest JWhiteEmployeeStatus.exe built by CI/CD.
    """
    exe_path = DOWNLOADS_DIR / "JWhiteEmployeeStatus.exe"

    if not exe_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Desktop app not available. Build may still be in progress.",
        )

    return FileResponse(
        path=str(exe_path),
        filename="JWhiteEmployeeStatus.exe",
        media_type="application/octet-stream",
    )


@app.get("/api/dashboard/download/desktop-app/info")
async def desktop_app_info():
    """Get information about the desktop app download."""
    exe_path = DOWNLOADS_DIR / "JWhiteEmployeeStatus.exe"

    if exe_path.exists():
        stat = exe_path.stat()
        return {
            "available": True,
            "filename": "JWhiteEmployeeStatus.exe",
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "download_url": "/api/dashboard/download/desktop-app",
        }
    else:
        return {
            "available": False,
            "message": "Desktop app not available. Build may still be in progress.",
        }
