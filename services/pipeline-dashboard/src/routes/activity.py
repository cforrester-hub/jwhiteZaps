"""Activity summary page routes — proxies to az-analyst API."""

import logging
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.templating import Jinja2Templates

from ..auth import get_current_user
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
templates = Jinja2Templates(directory="src/templates")

router = APIRouter()

PACIFIC = ZoneInfo("America/Los_Angeles")


async def _analyst_get(path: str, params: dict = None) -> dict | list | None:
    """Call the az-analyst REST API."""
    url = f"{settings.analyst_api_url}/api/analysis{path}"
    headers = {"X-API-Key": settings.analyst_api_key}
    if params:
        params = {k: v for k, v in params.items() if v is not None and v != ""}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code != 200:
                logger.warning(f"Analyst API {path} returned {r.status_code}: {r.text[:200]}")
                return None
            return r.json()
    except Exception as e:
        logger.error(f"Analyst API {path} failed: {e}")
        return None


def _today_pacific() -> date:
    """Get today's date in Pacific time."""
    from datetime import datetime
    return datetime.now(PACIFIC).date()


def _resolve_dates(preset: str, date_from: str = None, date_to: str = None) -> tuple[str, str]:
    """Resolve date preset or custom range to (date_from, date_to) strings."""
    today = _today_pacific()
    if preset == "yesterday":
        d = today - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    elif preset == "this_week":
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat(), today.isoformat()
    elif preset == "custom" and date_from and date_to:
        return date_from, date_to
    else:  # "today" or default
        return today.isoformat(), today.isoformat()


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------

@router.get("/pipeline/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    """Main activity summary page."""
    user = await get_current_user(request)
    if user is None:
        return templates.TemplateResponse("login.html", {"request": request, "error": ""})
    return templates.TemplateResponse("activity.html", {"request": request, "user": user})


# ---------------------------------------------------------------------------
# HTMX partial routes
# ---------------------------------------------------------------------------

@router.get("/pipeline/api/activity/summary", response_class=HTMLResponse)
async def activity_summary(
    request: Request,
    preset: str = "today",
    date_from: str = None,
    date_to: str = None,
    producer: str = None,
):
    """Summary cards partial."""
    user = await get_current_user(request)
    if user is None:
        return HTMLResponse("")

    df, dt = _resolve_dates(preset, date_from, date_to)
    data = await _analyst_get("/team-performance", {
        "date_from": df,
        "date_to": dt,
        "days": 1 if df == dt else None,
    })

    return templates.TemplateResponse("partials/activity_summary.html", {
        "request": request,
        "data": data,
        "date_from": df,
        "date_to": dt,
    })


@router.get("/pipeline/api/activity/new-leads", response_class=HTMLResponse)
async def activity_new_leads(
    request: Request,
    preset: str = "today",
    date_from: str = None,
    date_to: str = None,
    producer: str = None,
):
    """New leads by pipeline partial."""
    user = await get_current_user(request)
    if user is None:
        return HTMLResponse("")

    df, dt = _resolve_dates(preset, date_from, date_to)
    data = await _analyst_get("/funnel-performance", {
        "date_from": df,
        "date_to": dt,
        "group_by": "pipeline",
        "summary_only": "false",
        "producer": producer,
    })

    return templates.TemplateResponse("partials/activity_new_leads.html", {
        "request": request,
        "data": data,
        "date_from": df,
        "date_to": dt,
    })


@router.get("/pipeline/api/activity/producers", response_class=HTMLResponse)
async def activity_producers(
    request: Request,
    preset: str = "today",
    date_from: str = None,
    date_to: str = None,
    producer: str = None,
):
    """Producer activity table partial."""
    user = await get_current_user(request)
    if user is None:
        return HTMLResponse("")

    df, dt = _resolve_dates(preset, date_from, date_to)
    data = await _analyst_get("/funnel-performance", {
        "date_from": df,
        "date_to": dt,
        "group_by": "producer",
        "summary_only": "false",
        "producer": producer,
    })

    return templates.TemplateResponse("partials/activity_producers.html", {
        "request": request,
        "data": data,
        "date_from": df,
        "date_to": dt,
    })


@router.get("/pipeline/api/activity/coaching", response_class=HTMLResponse)
async def activity_coaching(
    request: Request,
    preset: str = "today",
    date_from: str = None,
    date_to: str = None,
    producer: str = None,
):
    """Coaching flags partial."""
    user = await get_current_user(request)
    if user is None:
        return HTMLResponse("")

    df, dt = _resolve_dates(preset, date_from, date_to)

    # Get coaching data for all producers or a specific one
    params = {
        "date_from": df,
        "date_to": dt,
        "summary_only": "true",
    }
    if producer:
        params["producer"] = producer

    # If no producer specified, get coaching for each active producer
    coaching_data = []
    if not producer:
        team = await _analyst_get("/team-performance", {"date_from": df, "date_to": dt})
        if team and team.get("producers"):
            for p in team["producers"]:
                name = p.get("firstname") or p.get("name", "").split()[0]
                if not name:
                    continue
                c = await _analyst_get("/coaching-analysis", {
                    "producer": name,
                    "date_from": df,
                    "date_to": dt,
                    "summary_only": "true",
                })
                if c and c.get("coaching_flag_summary"):
                    coaching_data.append({
                        "producer": name,
                        "flags": c["coaching_flag_summary"],
                        "summary": c.get("summary", {}),
                    })
    else:
        c = await _analyst_get("/coaching-analysis", params)
        if c and c.get("coaching_flag_summary"):
            coaching_data.append({
                "producer": producer,
                "flags": c["coaching_flag_summary"],
                "summary": c.get("summary", {}),
            })

    return templates.TemplateResponse("partials/activity_coaching.html", {
        "request": request,
        "coaching_data": coaching_data,
        "date_from": df,
        "date_to": dt,
    })
