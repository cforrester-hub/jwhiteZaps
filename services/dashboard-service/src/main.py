"""
Dashboard Service - Service Health Monitor

A simple dashboard that displays the health status of all microservices.
"""

import asyncio
import logging
from datetime import datetime
from string import Template
from typing import Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import get_settings

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Dashboard Service",
    description="Service health monitoring dashboard",
    version="1.0.0",
    docs_url="/api/dashboard/docs",
    redoc_url="/api/dashboard/redoc",
    openapi_url="/api/dashboard/openapi.json",
)


class ServiceStatus(BaseModel):
    """Status of a single service."""
    name: str
    url: str
    status: str  # "healthy", "unhealthy", "unknown"
    response_time_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: str


class DashboardData(BaseModel):
    """Complete dashboard data."""
    services: list[ServiceStatus]
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


async def get_all_service_statuses() -> DashboardData:
    """Check all services concurrently."""
    tasks = [
        check_service_health(name, url)
        for name, url in settings.services.items()
    ]

    statuses = await asyncio.gather(*tasks)
    healthy_count = sum(1 for s in statuses if s.status == "healthy")

    return DashboardData(
        services=list(statuses),
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
            max-width: 900px;
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

        .status-badge.healthy {{
            background: rgba(74, 222, 128, 0.2);
            color: #4ade80;
        }}

        .status-badge.unhealthy {{
            background: rgba(248, 113, 113, 0.2);
            color: #f87171;
        }}

        .status-badge.unknown {{
            background: rgba(251, 191, 36, 0.2);
            color: #fbbf24;
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

        <div class="services-grid">
            {service_cards_html}
        </div>

        <footer>
            <p class="refresh-note">Auto-refreshes every 30 seconds</p>
        </footer>
    </div>
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
