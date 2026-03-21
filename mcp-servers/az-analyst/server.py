"""MCP server for AZ Analyst - thin wrapper that calls the deployed REST API."""

import os

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("az-analyst")

API_BASE = os.environ.get("ANALYST_API_BASE", "https://jwhitezaps.atoaz.com/api/analysis")
API_KEY = os.environ.get("ANALYST_API_KEY", "")


async def _call_api(path: str, params: dict = None) -> str:
    """Call the deployed REST API and return the response text."""
    # Remove None values from params
    if params:
        params = {k: v for k, v in params.items() if v is not None and v != ""}
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(
            f"{API_BASE}{path}",
            params=params,
            headers={"X-API-Key": API_KEY},
        )
        if r.status_code != 200:
            return f"Error {r.status_code}: {r.text}"
        return r.text


@mcp.tool()
async def get_producer_activity(
    producer: str,
    date: str = "",
    days: int = 1,
    include_details: bool = False,
) -> str:
    """Analyze a producer's lead activity. Returns leads active on the given date with pipeline and status breakdown.

    Args:
        producer: Producer first name (e.g. "Gabriela", "Eric")
        date: Date in YYYY-MM-DD format. Defaults to today Pacific.
        days: Look back N days (default 1)
        include_details: If true, fetches notes and tasks from AZ API for top leads (slower, ~30s)
    """
    return await _call_api("/producer-activity", {
        "producer": producer,
        "date": date,
        "days": days,
        "include_details": str(include_details).lower(),
    })


@mcp.tool()
async def get_lead_detail(lead_id: int, include_notes: bool = True, include_tasks: bool = True) -> str:
    """Get detailed info for a specific lead including quotes, files, and optionally live notes/tasks from AgencyZoom.

    Returns synced quote data (carrier, product, premium, bundled status) and file references.
    Notes and tasks are fetched live from AZ API when requested.

    Args:
        lead_id: The AgencyZoom lead ID
        include_notes: Fetch live notes from AZ API (default true)
        include_tasks: Fetch live tasks from AZ API (default true)
    """
    return await _call_api(f"/lead/{lead_id}", {
        "include_notes": str(include_notes).lower(),
        "include_tasks": str(include_tasks).lower(),
    })


@mcp.tool()
async def pipeline_analytics(
    pipeline_id: str = "",
    producer: str = "",
    date_from: str = "",
    date_to: str = "",
) -> str:
    """Get pipeline-level analytics — lead counts by stage and status, conversion rates.

    Args:
        pipeline_id: Filter to a specific pipeline ID (optional)
        producer: Filter to a specific producer by first name (optional)
        date_from: Start date YYYY-MM-DD (optional)
        date_to: End date YYYY-MM-DD (optional)
    """
    return await _call_api("/pipeline-analytics", {
        "pipeline_id": pipeline_id,
        "producer": producer,
        "date_from": date_from,
        "date_to": date_to,
    })


@mcp.tool()
async def search_leads(query: str = "", phone: str = "", email: str = "", limit: int = 20) -> str:
    """Search leads by name, phone, or email.

    Args:
        query: Search by name (partial match)
        phone: Search by phone number (partial match)
        email: Search by email (partial match)
        limit: Max results (default 20)
    """
    return await _call_api("/search", {
        "query": query,
        "phone": phone,
        "email": email,
        "limit": limit,
    })


@mcp.tool()
async def get_tasks(producer: str, status: str = "all", date_from: str = "", date_to: str = "") -> str:
    """Get tasks for a producer from AgencyZoom (live API call).

    Args:
        producer: Producer first name
        status: Filter by status: "open", "completed", or "all" (default "all")
        date_from: Start date YYYY-MM-DD (optional)
        date_to: End date YYYY-MM-DD (optional)
    """
    return await _call_api("/tasks", {
        "producer": producer,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
    })


@mcp.tool()
async def quote_analysis(
    producer: str = "",
    pipeline_id: str = "",
    bundled_only: bool = False,
) -> str:
    """Analyze quoting patterns — which carriers, products, bundled vs mono-line, premiums.

    Uses synced quote data from the database (no live AZ API calls, fast).

    Args:
        producer: Filter by producer first name (optional)
        pipeline_id: Filter by pipeline ID (optional)
        bundled_only: If true, only show leads with multiple product lines quoted
    """
    return await _call_api("/quote-analysis", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "bundled_only": str(bundled_only).lower(),
    })


@mcp.tool()
async def team_performance(
    pipeline_id: str = "",
    date_from: str = "",
    date_to: str = "",
    days: int = 30,
) -> str:
    """Get per-producer performance breakdown: close rates, lead counts, status splits, new lead aging.

    Returns all active producers ranked by close rate. Includes:
    - new_this_period vs new_backlog (true new leads vs stale leads still in "new" status)
    - new_aging buckets (0-1 days, 2-3 days, 4-7 days, 8-14 days, 15+ days in stage)
    Great for team comparisons, leaderboards, and pipeline hygiene analysis.

    Args:
        pipeline_id: Filter to a specific pipeline ID (optional)
        date_from: Start date YYYY-MM-DD (optional, defaults to 30 days back)
        date_to: End date YYYY-MM-DD (optional, defaults to today)
        days: Look back N days if date_from not set (default 30)
    """
    return await _call_api("/team-performance", {
        "pipeline_id": pipeline_id,
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
    })


if __name__ == "__main__":
    mcp.run()
