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
    producer: str = "",
    date: str = "",
    days: int = 1,
    include_details: bool = False,
    summary_only: bool = False,
    group_by_day: bool = False,
) -> str:
    """Analyze lead activity. Omit producer for company-wide view, or specify a name for one producer.

    Args:
        producer: Producer first name (e.g. "Gabriela"). Omit or empty for company-wide.
        date: Date in YYYY-MM-DD format. Defaults to today Pacific.
        days: Look back N days (default 1)
        include_details: If true, fetches notes and tasks from AZ API for top leads (slower, ~30s)
        summary_only: If true, return only summary counts without per-lead list (faster)
        group_by_day: If true, break down activity counts by day within the date range
    """
    return await _call_api("/producer-activity", {
        "producer": producer,
        "date": date,
        "days": days,
        "include_details": str(include_details).lower(),
        "summary_only": str(summary_only).lower(),
        "group_by_day": str(group_by_day).lower(),
    })


@mcp.tool()
async def get_lead_detail(lead_id: int, include_notes: bool = True, include_tasks: bool = True) -> str:
    """Get detailed info for a specific lead including quotes, opportunities, files, and optionally live notes/tasks.

    Returns synced data: quotes (carrier, product, premium, bundled status),
    opportunities (carrier, product line, premium, status), and file references.
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
    pipeline_name: str = "",
    lead_source: str = "",
    source_group: str = "",
    date_from: str = "",
    date_to: str = "",
    days: int = 0,
    bundled_only: bool = False,
    summary_only: bool = False,
) -> str:
    """Analyze quoting patterns — which carriers, products, bundled vs mono-line, premiums.

    Searches ALL leads with quote records regardless of lead status, so it catches
    quoting activity even when producers haven't updated statuses. Returns a
    status_mismatch count showing leads with quotes but not in QUOTED/WON status
    (indicates pipeline discipline issues).
    Use summary_only=true for aggregate stats without per-lead detail (recommended for large datasets).

    Args:
        producer: Filter by producer first name (optional)
        pipeline_id: Filter by pipeline ID (optional)
        pipeline_name: Filter by pipeline name, partial match (optional)
        lead_source: Filter by lead source name (optional)
        source_group: Filter by classified source group: vendor_lead, inbound, book, referral, targeted, partner (optional)
        date_from: Start date YYYY-MM-DD (optional)
        date_to: End date YYYY-MM-DD (optional)
        days: Look back N days (shortcut for date_from, ignored if date_from set)
        bundled_only: If true, only show leads with multiple product lines quoted
        summary_only: If true, return only summary stats without per-lead detail (faster)
    """
    return await _call_api("/quote-analysis", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "lead_source": lead_source,
        "source_group": source_group,
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
        "bundled_only": str(bundled_only).lower(),
        "summary_only": str(summary_only).lower(),
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


@mcp.tool()
async def get_funnel_performance(
    producer: str = "",
    pipeline_id: str = "",
    pipeline_name: str = "",
    lead_source: str = "",
    source_group: str = "",
    channel_type: str = "",
    date_from: str = "",
    date_to: str = "",
    days: int = 30,
    group_by: str = "",
    report_mode: str = "standard",
    summary_only: bool = True,
    include_leads: bool = False,
) -> str:
    """Executive funnel metrics — quote rates, close rates, speed-to-quote, bundle analysis.

    Filters on enter_stage_date (when lead entered funnel). Use group_by for breakdowns
    by producer, pipeline, source, day, or week. report_mode controls rate denominators:
    standard (rates from leads_entered) or internet (rates from contacted/quoted).

    Args:
        producer: Filter by producer first name (optional)
        pipeline_name: Filter by pipeline name, partial match (optional)
        pipeline_id: Filter by pipeline ID (optional)
        lead_source: Filter by lead source name (optional)
        source_group: Filter by classified source group: vendor_lead, inbound, book, referral, targeted, partner (optional)
        channel_type: Filter by channel: internet, inbound, internal, reactivation, outbound, etc. (optional)
        date_from: Start date YYYY-MM-DD (optional, defaults to 30 days back)
        date_to: End date YYYY-MM-DD (optional)
        days: Look back N days if date_from not set (default 30)
        group_by: Break down by: producer, pipeline, source, day, week (optional)
        report_mode: standard (default) or internet (changes denominator logic)
        summary_only: Omit groups array (default true for safety)
        include_leads: Include per-lead detail (default false)
    """
    return await _call_api("/funnel-performance", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "lead_source": lead_source,
        "source_group": source_group,
        "channel_type": channel_type,
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
        "group_by": group_by,
        "report_mode": report_mode,
        "summary_only": str(summary_only).lower(),
        "include_leads": str(include_leads).lower(),
    })


@mcp.tool()
async def get_data_quality_report(
    producer: str = "",
    pipeline_id: str = "",
    days: int = 90,
) -> str:
    """Data quality diagnostics — surfaces pipeline discipline issues and missing data.

    Checks for: quoted leads with wrong status, won without quotes, expired with quotes,
    missing timestamps, stuck leads (14+ days in NEW), and timeline anomalies.
    Returns health score, issue counts by category, and sample leads per issue.

    Args:
        producer: Filter by producer first name (optional)
        pipeline_id: Filter by pipeline ID (optional)
        days: How far back to scan (default 90)
    """
    return await _call_api("/data-quality", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "days": days,
    })


@mcp.tool()
async def get_pipeline_compliance(
    date_from: str,
    date_to: str,
    producer: str = "",
    pipeline_id: str = "",
    pipeline_name: str = "",
    summary_only: bool = True,
) -> str:
    """Quote compliance metrics for a pipeline — quote rate, compliance status, unquoted leads.

    Returns passing/warning/failing status based on pipeline intent type thresholds.
    High-intent pipelines (Call/Walk In) expect 90%+ quote rates.
    Use summary_only=false to see the list of unquoted leads.

    Args:
        date_from: Start date YYYY-MM-DD (required, filters on enter_stage_date)
        date_to: End date YYYY-MM-DD (required)
        producer: Filter by producer first name (optional)
        pipeline_id: Filter by pipeline ID (optional)
        pipeline_name: Filter by pipeline name, partial match (optional)
        summary_only: Omit unquoted lead list (default true)
    """
    return await _call_api("/pipeline-compliance", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "date_from": date_from,
        "date_to": date_to,
        "summary_only": str(summary_only).lower(),
    })


@mcp.tool()
async def get_lost_deal_analysis(
    date_from: str,
    date_to: str,
    producer: str = "",
    pipeline_id: str = "",
    pipeline_name: str = "",
    include_recoverable: bool = True,
    summary_only: bool = True,
) -> str:
    """Audit quoted leads that didn't close — post-quote leakage, failure reasons, recoverable leads.

    Shows close rate among quoted leads, leakage percentage, and identifies
    leads that may be recoverable (quoted, not won, recent activity).

    Args:
        date_from: Start date YYYY-MM-DD (required)
        date_to: End date YYYY-MM-DD (required)
        producer: Filter by producer first name (optional)
        pipeline_id: Filter by pipeline ID (optional)
        pipeline_name: Filter by pipeline name, partial match (optional)
        include_recoverable: Include recoverable lead identification (default true)
        summary_only: Omit per-lead detail lists (default true)
    """
    return await _call_api("/lost-deal-analysis", {
        "producer": producer,
        "pipeline_id": pipeline_id,
        "pipeline_name": pipeline_name,
        "date_from": date_from,
        "date_to": date_to,
        "include_recoverable": str(include_recoverable).lower(),
        "summary_only": str(summary_only).lower(),
    })


@mcp.tool()
async def get_producer_scorecard(
    producer: str,
    date_from: str,
    date_to: str,
) -> str:
    """One-response KPI summary for a producer across all pipelines with team rankings.

    Returns quote rate, close rate, leakage metrics, timing, per-pipeline breakdown,
    and rank vs other producers on key metrics.

    Args:
        producer: Producer first name (required)
        date_from: Start date YYYY-MM-DD (required)
        date_to: End date YYYY-MM-DD (required)
    """
    return await _call_api("/producer-scorecard", {
        "producer": producer,
        "date_from": date_from,
        "date_to": date_to,
    })


@mcp.tool()
async def get_coaching_analysis(
    producer: str,
    date_from: str = "",
    date_to: str = "",
    days: int = 1,
    pipeline_name: str = "",
    pipeline_id: str = "",
    include_note_content: bool = True,
    max_notes_per_lead: int = 10,
    summary_only: bool = False,
) -> str:
    """Coaching analysis — surfaces communication patterns, follow-up gaps, and coaching opportunities.

    Returns per-lead activity breakdown with notes (emails, texts, calls), tasks,
    timing metrics, and coaching flags (no_contact, slow_response, quoted_no_followup,
    overdue_tasks, missing_tasks). Use summary_only=true for high-volume producers.
    Use pipeline_name to scope to a specific pipeline (e.g. "NPL Internet").

    Args:
        producer: Producer first name (required)
        date_from: Start date YYYY-MM-DD (optional, defaults to yesterday)
        date_to: End date YYYY-MM-DD (optional, defaults to date_from)
        days: Look back N days if date_from not set (default 1 = yesterday)
        pipeline_name: Filter by pipeline name, partial match (optional)
        pipeline_id: Filter by pipeline ID (optional)
        include_note_content: Include note/email/text body text (default true)
        max_notes_per_lead: Cap notes per lead to control response size (default 10)
        summary_only: Return only summary and flag counts, omit per-lead detail (default false)
    """
    return await _call_api("/coaching-analysis", {
        "producer": producer,
        "date_from": date_from,
        "date_to": date_to,
        "days": days,
        "pipeline_name": pipeline_name,
        "pipeline_id": pipeline_id,
        "include_note_content": str(include_note_content).lower(),
        "max_notes_per_lead": max_notes_per_lead,
        "summary_only": str(summary_only).lower(),
    })


if __name__ == "__main__":
    mcp.run()
