"""Analysis REST API endpoints."""

import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select

from ..auth import verify_api_key
from ..az_client import (
    fetch_lead_detail,
    fetch_lead_notes,
    fetch_lead_tasks,
    search_tasks,
    system_login,
)
from ..config import get_settings
from ..database import Employee, Lead, LeadFile, LeadNote, LeadOpportunity, LeadQuote, LeadTask, Pipeline, Stage, async_session
from ..normalization import classify_pipeline, classify_source, get_compliance_status

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

STATUS_MAP = {0: "new", 1: "quoted", 2: "won", 3: "lost", 4: "contacted", 5: "expired"}


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

def _parse_date_str(s: str | None) -> datetime | None:
    """Parse a date string into datetime. Handles 'YYYY-MM-DD' and 'YYYY-MM-DD HH:MM:SS'."""
    if not s or len(s) < 10:
        return None
    try:
        if len(s) >= 19:
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return datetime.strptime(s[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _hours_between(start: str | None, end: str | None) -> float | None:
    """Calculate hours between two date strings. Returns None if either is missing or end < start."""
    s = _parse_date_str(start)
    e = _parse_date_str(end)
    if not s or not e or e < s:
        return None
    return round((e - s).total_seconds() / 3600, 1)


def _timing_stats(values: list[float]) -> dict:
    """Compute median, average, and sample size for a list of hour values."""
    clean = [v for v in values if v is not None]
    if not clean:
        return {"median_hours": None, "avg_hours": None, "sample_size": 0}
    return {
        "median_hours": round(statistics.median(clean), 1),
        "avg_hours": round(sum(clean) / len(clean), 1),
        "sample_size": len(clean),
    }


async def _load_name_maps(session) -> tuple[dict, dict]:
    """Load pipeline and stage name lookup maps from DB."""
    pipeline_result = await session.execute(select(Pipeline))
    pipelines_map = {p.id: p.name for p in pipeline_result.scalars().all()}

    stage_result = await session.execute(select(Stage))
    stages_map = {s.id: s.name for s in stage_result.scalars().all()}

    return pipelines_map, stages_map


async def _get_quoted_lead_ids(session, lead_ids: list[int] = None) -> set[int]:
    """Get set of lead IDs that have quote records in pd_lead_quotes.

    A lead is considered 'effectively quoted' if it has quote records OR quote_date is set.
    This is more reliable than the status field which is never set to QUOTED in AZ.
    """
    query = select(LeadQuote.lead_id).distinct()
    if lead_ids is not None:
        query = query.where(LeadQuote.lead_id.in_(lead_ids))
    result = await session.execute(query)
    return {row[0] for row in result}


def _is_effectively_quoted(lead: Lead, quoted_lead_ids: set[int]) -> bool:
    """Check if a lead has been quoted based on quote records or quote_date."""
    return lead.id in quoted_lead_ids or bool(lead.quote_date)


def _serialize_lead(lead: Lead, effectively_quoted: bool = False,
                    pipelines_map: dict = None, stages_map: dict = None) -> dict:
    """Convert a Lead ORM object to a JSON-serializable dict.

    pipelines_map/stages_map resolve names when workflow_name/workflow_stage_name are null.
    """
    pipeline_name = lead.workflow_name
    if not pipeline_name and pipelines_map and lead.pipeline_id:
        pipeline_name = pipelines_map.get(lead.pipeline_id)

    stage_name = lead.workflow_stage_name
    if not stage_name and stages_map and lead.stage_id:
        stage_info = stages_map.get(lead.stage_id)
        if isinstance(stage_info, dict):
            stage_name = stage_info.get("name")
        elif isinstance(stage_info, str):
            stage_name = stage_info

    return {
        "id": lead.id,
        "name": f"{lead.firstname or ''} {lead.lastname or ''}".strip(),
        "firstname": lead.firstname,
        "lastname": lead.lastname,
        "pipeline": pipeline_name,
        "pipeline_id": lead.pipeline_id,
        "stage": stage_name,
        "stage_id": lead.stage_id,
        "status": STATUS_MAP.get(lead.status, "unknown"),
        "status_code": lead.status,
        "last_activity": lead.last_activity_date,
        "create_date": lead.create_date,
        "enter_stage_date": lead.enter_stage_date,
        "contact_date": lead.contact_date,
        "lead_source": lead.lead_source_name,
        "lead_source_id": lead.lead_source_id,
        "lead_type": lead.lead_type,
        "premium": lead.premium,
        "quoted": lead.quoted,
        "phone": lead.phone,
        "email": lead.email,
        "assigned_to": lead.assigned_to,
        "assign_to_firstname": lead.assign_to_firstname,
        "assign_to_lastname": lead.assign_to_lastname,
        # New high-value fields
        "street_address": lead.street_address,
        "city": lead.city,
        "state": lead.state,
        "zip_code": lead.zip_code,
        "sold_date": lead.sold_date,
        "x_date": lead.x_date,
        "quote_date": lead.quote_date,
        "customer_id": lead.customer_id,
        "tag_names": lead.tag_names,
        "effectively_quoted": effectively_quoted,
    }


def _serialize_quote(q: LeadQuote) -> dict:
    """Convert a LeadQuote ORM object to a JSON-serializable dict."""
    return {
        "id": q.id,
        "lead_id": q.lead_id,
        "carrier_name": q.carrier_name,
        "product_name": q.product_name,
        "premium": q.premium,
        "items": q.items,
        "sold": bool(q.sold) if q.sold is not None else None,
        "effective_date": q.effective_date,
        "potential_revenue": q.potential_revenue,
        "property_address": q.property_address,
    }


def _serialize_file(f: LeadFile) -> dict:
    """Convert a LeadFile ORM object to a JSON-serializable dict."""
    return {
        "id": f.id,
        "lead_id": f.lead_id,
        "title": f.title,
        "media_type": f.media_type,
        "file_type": f.file_type,
        "size": f.size,
        "create_date": f.create_date,
        "comments": f.comments,
    }


def _serialize_opportunity(o: LeadOpportunity) -> dict:
    """Convert a LeadOpportunity ORM object to a JSON-serializable dict."""
    return {
        "id": o.id,
        "lead_id": o.lead_id,
        "carrier_id": o.carrier_id,
        "product_line_id": o.product_line_id,
        "status": o.status,
        "premium": o.premium,
        "items": o.items,
        "property_address": o.property_address,
    }


def _today_pacific() -> date:
    """Get today's date in Pacific time."""
    return datetime.now(ZoneInfo(settings.az_timezone)).date()


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@router.get("/producer-activity", dependencies=[Depends(verify_api_key)])
async def producer_activity(
    producer: Optional[str] = Query(None, description="Producer firstname (omit for company-wide)"),
    date: Optional[str] = Query(None, description="Date (YYYY-MM-DD), defaults to today Pacific"),
    days: int = Query(1, description="Look back N days", ge=1, le=90),
    include_details: bool = Query(False, description="Fetch notes/tasks from AZ API for top leads"),
    summary_only: bool = Query(False, description="Omit leads array (faster for large queries)"),
    group_by_day: bool = Query(False, description="Add by_date daily activity counts"),
):
    """Analyze lead activity for a given date range. Omit producer for company-wide view."""
    # Parse date range
    if date:
        try:
            end_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")
    else:
        end_date = _today_pacific()

    start_date = end_date - timedelta(days=days - 1)

    async with async_session() as session:
        # Find producer info if specified
        employee = None
        if producer:
            emp_result = await session.execute(
                select(Employee).where(
                    func.lower(Employee.firstname) == producer.lower()
                )
            )
            employee = emp_result.scalar_one_or_none()

        # Query leads by activity date range, optionally filtered by producer
        query = select(Lead).where(
            Lead.last_activity_date >= start_date.isoformat(),
            Lead.last_activity_date <= end_date.isoformat() + "T23:59:59",
        )
        if producer:
            query = query.where(func.lower(Lead.assign_to_firstname) == producer.lower())
        query = query.order_by(Lead.last_activity_date.desc())

        result = await session.execute(query)
        leads = result.scalars().all()

        # Get set of lead IDs that have actual quote records
        lead_ids = [l.id for l in leads]
        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()

        # Count by status, using real quoting and contact detection
        # AZ never reliably sets status=1 (QUOTED) or status=4 (CONTACTED)
        # Use quote records/quote_date for quoted, contact_date for contacted
        status_counts = {"new": 0, "quoted": 0, "won": 0, "lost": 0, "contacted": 0, "expired": 0}
        for lead in leads:
            if lead.status == 2:
                status_counts["won"] += 1
            elif lead.status == 3:
                status_counts["lost"] += 1
            elif lead.status == 5:
                status_counts["expired"] += 1
            elif _is_effectively_quoted(lead, quoted_lead_ids):
                status_counts["quoted"] += 1
            elif lead.contact_date:
                status_counts["contacted"] += 1
            else:
                status_counts["new"] += 1

        # Group by pipeline
        pipeline_groups = {}
        for lead in leads:
            pname = lead.workflow_name or "Unknown"
            if pname not in pipeline_groups:
                pipeline_groups[pname] = {"name": pname, "active": 0}
            pipeline_groups[pname]["active"] += 1

        # Get total assigned per pipeline
        for pname in pipeline_groups:
            count_query = select(func.count(Lead.id)).where(Lead.workflow_name == pname)
            if producer:
                count_query = count_query.where(func.lower(Lead.assign_to_firstname) == producer.lower())
            count_result = await session.execute(count_query)
            pipeline_groups[pname]["total_assigned"] = count_result.scalar() or 0

        # Serialize leads
        if summary_only:
            serialized_leads = []
        else:
            serialized_leads = [_serialize_lead(l, _is_effectively_quoted(l, quoted_lead_ids)) for l in leads]

        # Optionally fetch live details for top leads
        if not summary_only and include_details and leads:
            try:
                jwt = await system_login()
                # Cap leads fetched so we stay under max_live_api_calls (2 calls per lead: notes + tasks)
                max_leads = settings.max_live_api_calls // 2
                top_leads = leads[:max_leads]
                api_calls_made = 0
                for i, lead in enumerate(top_leads):
                    if api_calls_made >= settings.max_live_api_calls:
                        logger.info(f"Hit max_live_api_calls ({settings.max_live_api_calls}), stopping detail fetch")
                        break
                    try:
                        notes = await fetch_lead_notes(jwt, lead.id)
                        api_calls_made += 1
                        tasks = await fetch_lead_tasks(jwt, lead.id)
                        api_calls_made += 1
                        serialized_leads[i]["notes"] = notes
                        serialized_leads[i]["tasks"] = tasks
                    except Exception as e:
                        logger.warning(f"Failed to fetch details for lead {lead.id}: {e}")
                        serialized_leads[i]["notes"] = []
                        serialized_leads[i]["tasks"] = []
                        serialized_leads[i]["detail_error"] = str(e)
            except Exception as e:
                logger.error(f"Failed to authenticate with AZ API: {e}")

    response = {
        "producer": {
            "firstname": employee.firstname if employee else (producer or "All"),
            "lastname": employee.lastname if employee else None,
            "id": employee.id if employee else None,
        } if producer else {"firstname": "All", "lastname": "Company-wide", "id": None},
        "date_range": {
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        },
        "summary": {
            "leads_active": len(leads),
            **status_counts,
        },
        "leads": serialized_leads,
        "by_pipeline": list(pipeline_groups.values()),
    }

    if group_by_day:
        by_date = {}
        for lead in leads:
            day_key = (lead.last_activity_date or "")[:10]
            if day_key:
                by_date[day_key] = by_date.get(day_key, 0) + 1
        response["by_date"] = [{"date": k, "count": v} for k, v in sorted(by_date.items())]

    return response


@router.get("/lead/{lead_id}", dependencies=[Depends(verify_api_key)])
async def lead_detail(
    lead_id: int,
    include_notes: bool = Query(True),
    include_tasks: bool = Query(True),
):
    """Get detailed info for a specific lead, with optional live notes/tasks."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()

    if not lead:
        raise HTTPException(404, "Lead not found")

    response = {"lead": _serialize_lead(lead)}

    # Include synced quotes and files from DB
    async with async_session() as session:
        quote_result = await session.execute(
            select(LeadQuote).where(LeadQuote.lead_id == lead_id)
        )
        quotes = quote_result.scalars().all()
        response["quotes"] = [_serialize_quote(q) for q in quotes]
        response["quote_count"] = len(quotes)
        response["is_bundled"] = len(set(q.product_name for q in quotes if q.product_name)) > 1

        file_result = await session.execute(
            select(LeadFile).where(LeadFile.lead_id == lead_id)
        )
        files = file_result.scalars().all()
        response["files"] = [_serialize_file(f) for f in files]

        opp_result = await session.execute(
            select(LeadOpportunity).where(LeadOpportunity.lead_id == lead_id)
        )
        opportunities = opp_result.scalars().all()
        response["opportunities"] = [_serialize_opportunity(o) for o in opportunities]

    if include_notes or include_tasks:
        try:
            jwt = await system_login()
            if include_notes:
                try:
                    response["notes"] = await fetch_lead_notes(jwt, lead_id)
                except Exception as e:
                    logger.warning(f"Failed to fetch notes for lead {lead_id}: {e}")
                    response["notes"] = []
                    response["notes_error"] = str(e)
            if include_tasks:
                try:
                    response["tasks"] = await fetch_lead_tasks(jwt, lead_id)
                except Exception as e:
                    logger.warning(f"Failed to fetch tasks for lead {lead_id}: {e}")
                    response["tasks"] = []
                    response["tasks_error"] = str(e)
        except Exception as e:
            logger.error(f"Failed to authenticate with AZ API: {e}")
            response["api_error"] = str(e)

    return response


@router.get("/pipeline-analytics", dependencies=[Depends(verify_api_key)])
async def pipeline_analytics(
    pipeline_id: Optional[str] = Query(None),
    producer: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Pipeline-level analytics from synced data. No live AZ API calls."""
    async with async_session() as session:
        # Build base query
        query = select(Lead)
        conditions = []

        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)
        if producer:
            conditions.append(func.lower(Lead.assign_to_firstname) == producer.lower())
        if date_from:
            conditions.append(Lead.last_activity_date >= date_from)
        if date_to:
            conditions.append(Lead.last_activity_date <= date_to + "T23:59:59")

        if conditions:
            query = query.where(*conditions)

        result = await session.execute(query)
        leads = result.scalars().all()

        # Get pipelines for names
        pipeline_result = await session.execute(select(Pipeline))
        pipelines_map = {p.id: p.name for p in pipeline_result.scalars().all()}

        # Get stages for names
        stage_result = await session.execute(select(Stage))
        stages_map = {s.id: {"name": s.name, "pipeline_id": s.pipeline_id} for s in stage_result.scalars().all()}

    # Group by pipeline
    pipeline_data = {}
    for lead in leads:
        pid = lead.pipeline_id or "unknown"
        if pid not in pipeline_data:
            pipeline_data[pid] = {
                "id": pid,
                "name": pipelines_map.get(pid, lead.workflow_name or "Unknown"),
                "total": 0,
                "by_stage": {},
                "by_status": {"new": 0, "quoted": 0, "won": 0, "lost": 0, "contacted": 0, "expired": 0},
            }
        pd = pipeline_data[pid]
        pd["total"] += 1

        # By stage
        stage_name = lead.workflow_stage_name or "Unknown"
        pd["by_stage"][stage_name] = pd["by_stage"].get(stage_name, 0) + 1

        # By status
        status_name = STATUS_MAP.get(lead.status, "unknown")
        if status_name in pd["by_status"]:
            pd["by_status"][status_name] += 1

    # Format output
    pipelines_out = []
    total_leads = 0
    total_won = 0
    for pd in pipeline_data.values():
        won = pd["by_status"]["won"]
        total = pd["total"]
        pipelines_out.append({
            "id": pd["id"],
            "name": pd["name"],
            "total": total,
            "by_stage": [{"stage": k, "count": v} for k, v in pd["by_stage"].items()],
            "by_status": pd["by_status"],
            "conversion_rate": round(won / total, 2) if total > 0 else 0,
        })
        total_leads += total
        total_won += won

    return {
        "pipelines": pipelines_out,
        "totals": {
            "leads": total_leads,
            "won": total_won,
            "conversion_rate": round(total_won / total_leads, 2) if total_leads > 0 else 0,
        },
    }


@router.get("/tasks", dependencies=[Depends(verify_api_key)])
async def get_tasks(
    producer: str = Query(..., description="Producer firstname"),
    status: str = Query("all", description="open, completed, or all"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    """Get tasks for a producer. Live AZ API call."""
    # Look up employee ID
    async with async_session() as session:
        emp_result = await session.execute(
            select(Employee).where(
                func.lower(Employee.firstname) == producer.lower()
            )
        )
        employee = emp_result.scalar_one_or_none()

    if not employee:
        raise HTTPException(404, f"Producer '{producer}' not found")

    try:
        jwt = await system_login()
        tasks = await search_tasks(
            jwt,
            assignee_id=employee.id,
            date_from=date_from,
            date_to=date_to,
        )
    except Exception as e:
        logger.error(f"Failed to fetch tasks: {e}")
        raise HTTPException(502, f"Failed to fetch tasks from AgencyZoom: {e}")

    # Filter by status if needed
    if status == "open":
        tasks = [t for t in tasks if not t.get("completed", False) and t.get("status", "").lower() != "completed"]
    elif status == "completed":
        tasks = [t for t in tasks if t.get("completed", True) or t.get("status", "").lower() == "completed"]

    return {
        "producer": {
            "firstname": employee.firstname,
            "lastname": employee.lastname,
            "id": employee.id,
        },
        "task_count": len(tasks),
        "tasks": tasks,
    }


@router.get("/search", dependencies=[Depends(verify_api_key)])
async def search_leads(
    query: Optional[str] = Query(None, description="Search by name"),
    phone: Optional[str] = Query(None, description="Search by phone"),
    email: Optional[str] = Query(None, description="Search by email"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search leads by name, phone, or email from synced data."""
    if not query and not phone and not email:
        raise HTTPException(400, "At least one search parameter required (query, phone, or email)")

    async with async_session() as session:
        conditions = []
        if query:
            pattern = f"%{query}%"
            conditions.append(
                or_(
                    func.concat(Lead.firstname, ' ', Lead.lastname).ilike(pattern),
                    Lead.firstname.ilike(pattern),
                    Lead.lastname.ilike(pattern),
                )
            )
        if phone:
            conditions.append(Lead.phone.ilike(f"%{phone}%"))
        if email:
            conditions.append(Lead.email.ilike(f"%{email}%"))

        stmt = select(Lead).where(*conditions).order_by(Lead.last_activity_date.desc()).limit(limit)
        result = await session.execute(stmt)
        leads = result.scalars().all()

    return {
        "count": len(leads),
        "leads": [_serialize_lead(l) for l in leads],
    }


@router.get("/team-performance", dependencies=[Depends(verify_api_key)])
async def team_performance(
    pipeline_id: Optional[str] = Query(None, description="Filter to a specific pipeline"),
    date_from: Optional[str] = Query(None, description="Activity date start YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="Activity date end YYYY-MM-DD"),
    days: int = Query(30, description="Look back N days (ignored if date_from set)", ge=1, le=365),
):
    """Per-producer performance breakdown: close rates, lead counts, status splits.

    Returns all active producers ranked by close rate.
    """
    # Compute date range
    if date_from:
        start = date_from
    else:
        start = (_today_pacific() - timedelta(days=days - 1)).isoformat()
    end = (date_to or _today_pacific().isoformat()) + "T23:59:59"

    async with async_session() as session:
        # Get active producers
        emp_result = await session.execute(
            select(Employee).where(Employee.is_producer == 1, Employee.is_active == 1)
        )
        producers = emp_result.scalars().all()

        # Get all leads in date range
        lead_query = select(Lead).where(
            Lead.last_activity_date >= start,
            Lead.last_activity_date <= end,
        )
        if pipeline_id:
            lead_query = lead_query.where(Lead.pipeline_id == pipeline_id)

        lead_result = await session.execute(lead_query)
        leads = lead_result.scalars().all()

        # Get set of lead IDs that have actual quote records
        all_lead_ids = [l.id for l in leads]
        quoted_lead_ids = await _get_quoted_lead_ids(session, all_lead_ids) if all_lead_ids else set()

    # Build producer lookup
    producer_map = {p.id: p for p in producers}

    # Helper: compute days since enter_stage_date relative to today
    today = _today_pacific()

    def _days_in_stage(lead) -> int | None:
        """Days since lead entered current stage."""
        if not lead.enter_stage_date or len(lead.enter_stage_date) < 10:
            return None
        try:
            entered = datetime.strptime(lead.enter_stage_date[:10], "%Y-%m-%d").date()
            return (today - entered).days
        except (ValueError, TypeError):
            return None

    def _entered_in_range(lead) -> bool:
        """True if enter_stage_date falls within the query date range."""
        if not lead.enter_stage_date:
            return False
        return lead.enter_stage_date >= start and lead.enter_stage_date <= end

    # Group leads by assigned_to
    by_producer = {}
    for lead in leads:
        pid = lead.assigned_to
        if pid not in by_producer:
            prod = producer_map.get(pid)
            by_producer[pid] = {
                "id": pid,
                "name": f"{prod.firstname or ''} {prod.lastname or ''}".strip() if prod else f"Unknown ({pid})",
                "firstname": prod.firstname if prod else None,
                "lastname": prod.lastname if prod else None,
                "total": 0,
                "new": 0,
                "quoted": 0,
                "won": 0,
                "lost": 0,
                "contacted": 0,
                "expired": 0,
                "new_this_period": 0,
                "new_backlog": 0,
                "new_aging": {"0-1_days": 0, "2-3_days": 0, "4-7_days": 0, "8-14_days": 0, "15+_days": 0},
            }
        entry = by_producer[pid]
        entry["total"] += 1
        if lead.status == 2:
            entry["won"] += 1
        elif lead.status == 3:
            entry["lost"] += 1
        elif lead.status == 5:
            entry["expired"] += 1
        elif _is_effectively_quoted(lead, quoted_lead_ids):
            entry["quoted"] += 1
        elif lead.contact_date:
            entry["contacted"] += 1
        else:
            entry["new"] += 1

        # New lead breakdown — only for leads that are truly new (not contacted or quoted)
        if lead.status == 0 and not _is_effectively_quoted(lead, quoted_lead_ids) and not lead.contact_date:
            if _entered_in_range(lead):
                entry["new_this_period"] += 1
            else:
                entry["new_backlog"] += 1

            days_in = _days_in_stage(lead)
            if days_in is not None:
                if days_in <= 1:
                    entry["new_aging"]["0-1_days"] += 1
                elif days_in <= 3:
                    entry["new_aging"]["2-3_days"] += 1
                elif days_in <= 7:
                    entry["new_aging"]["4-7_days"] += 1
                elif days_in <= 14:
                    entry["new_aging"]["8-14_days"] += 1
                else:
                    entry["new_aging"]["15+_days"] += 1

    # Compute close rates and sort
    results = []
    for entry in by_producer.values():
        total = entry["total"]
        won = entry["won"]
        lost = entry["lost"]
        decided = won + lost
        entry["close_rate"] = round(won / decided, 3) if decided > 0 else 0
        entry["close_rate_pct"] = f"{entry['close_rate'] * 100:.1f}%"
        entry["decided"] = decided
        results.append(entry)

    results.sort(key=lambda x: (-x["close_rate"], -x["won"]))

    # Team totals
    team_total = sum(e["total"] for e in results)
    team_won = sum(e["won"] for e in results)
    team_lost = sum(e["lost"] for e in results)
    team_decided = team_won + team_lost
    team_new = sum(e["new"] for e in results)
    team_new_this_period = sum(e["new_this_period"] for e in results)
    team_new_backlog = sum(e["new_backlog"] for e in results)

    return {
        "date_range": {"from": start, "to": date_to or _today_pacific().isoformat()},
        "producers": results,
        "team_totals": {
            "total_leads": team_total,
            "won": team_won,
            "lost": team_lost,
            "decided": team_decided,
            "close_rate": round(team_won / team_decided, 3) if team_decided > 0 else 0,
            "close_rate_pct": f"{round(team_won / team_decided * 100, 1) if team_decided > 0 else 0}%",
            "producers_count": len(results),
            "new": team_new,
            "new_this_period": team_new_this_period,
            "new_backlog": team_new_backlog,
        },
    }


@router.get("/quote-analysis", dependencies=[Depends(verify_api_key)])
async def quote_analysis(
    producer: Optional[str] = Query(None, description="Filter by producer firstname"),
    pipeline_id: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline name (partial match)"),
    lead_source: Optional[str] = Query(None, description="Filter by lead_source_name"),
    source_group: Optional[str] = Query(None, description="Filter by classified source group"),
    date_from: Optional[str] = Query(None, description="Filter by last_activity_date start YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="Filter by last_activity_date end YYYY-MM-DD"),
    days: int = Query(0, description="Look back N days (shortcut for date_from, ignored if date_from set)", ge=0, le=365),
    bundled_only: bool = Query(False, description="Only show leads with multiple product lines"),
    summary_only: bool = Query(False, description="Return only summary stats, omit per-lead detail (faster, smaller response)"),
):
    """Analyze quoting patterns from synced quote data. No live AZ API calls.

    Searches ALL leads that have quote records (regardless of lead status), so it
    catches quoting activity even when producers haven't updated the lead status to QUOTED.
    Includes a status_mismatch count showing leads with quotes but not in QUOTED/WON status.
    Use summary_only=true for aggregate stats without per-lead data (recommended for large datasets).
    """
    # Compute date range
    start = None
    end = None
    if date_from:
        start = date_from
    elif days > 0:
        start = (_today_pacific() - timedelta(days=days - 1)).isoformat()
    if date_to:
        end = date_to + "T23:59:59"
    elif start:
        end = _today_pacific().isoformat() + "T23:59:59"

    async with async_session() as session:
        # Find all leads that have quote records OR quote_date set
        leads_with_quotes_q = select(LeadQuote.lead_id).distinct()
        leads_with_quotes_result = await session.execute(leads_with_quotes_q)
        lead_ids_with_quotes = {row[0] for row in leads_with_quotes_result}

        # Also include leads with quote_date set (even if no quote records yet)
        quote_date_q = select(Lead.id).where(Lead.quote_date != None)
        quote_date_result = await session.execute(quote_date_q)
        lead_ids_with_quote_date = {row[0] for row in quote_date_result}

        effectively_quoted_ids = lead_ids_with_quotes | lead_ids_with_quote_date

        if not effectively_quoted_ids:
            return {"summary": {"total": 0, "bundled": 0, "mono_line": 0, "by_carrier": [], "by_product": []}}

        # Get the lead records, applying filters
        lead_query = select(Lead).where(Lead.id.in_(effectively_quoted_ids))
        if producer:
            lead_query = lead_query.where(
                func.lower(Lead.assign_to_firstname) == producer.lower()
            )
        if pipeline_id:
            lead_query = lead_query.where(Lead.pipeline_id == pipeline_id)
        if pipeline_name:
            lead_query = lead_query.where(Lead.workflow_name.ilike(f"%{pipeline_name}%"))
        if lead_source:
            lead_query = lead_query.where(Lead.lead_source_name == lead_source)
        if start:
            lead_query = lead_query.where(Lead.last_activity_date >= start)
        if end:
            lead_query = lead_query.where(Lead.last_activity_date <= end)

        lead_result = await session.execute(lead_query)
        leads = lead_result.scalars().all()
        lead_ids = [l.id for l in leads]

        if source_group:
            leads = [l for l in leads if classify_source(l.lead_source_name) == source_group]
            lead_ids = [l.id for l in leads]

        if not lead_ids:
            return {"summary": {"total": 0, "bundled": 0, "mono_line": 0, "by_carrier": [], "by_product": []}}

        # Fetch all quotes for these leads
        quote_result = await session.execute(
            select(LeadQuote).where(LeadQuote.lead_id.in_(lead_ids))
        )
        all_quotes = quote_result.scalars().all()

        # Group quotes by lead
        quotes_by_lead = {}
        for q in all_quotes:
            quotes_by_lead.setdefault(q.lead_id, []).append(q)

    # Build response
    lead_data = []
    carrier_counts = {}
    product_counts = {}
    bundled_count = 0
    mono_count = 0
    has_quote_records = 0
    quote_date_only = 0

    for lead in leads:
        lead_quotes = quotes_by_lead.get(lead.id, [])
        effectively_quoted = lead.id in lead_ids_with_quotes or bool(lead.quote_date)

        if lead_quotes:
            has_quote_records += 1
            product_names = set(q.product_name for q in lead_quotes if q.product_name)
            is_bundled = len(product_names) > 1

            if bundled_only and not is_bundled:
                continue

            if is_bundled:
                bundled_count += 1
            else:
                mono_count += 1

            for q in lead_quotes:
                if q.carrier_name:
                    carrier_counts[q.carrier_name] = carrier_counts.get(q.carrier_name, 0) + 1
                if q.product_name:
                    product_counts[q.product_name] = product_counts.get(q.product_name, 0) + 1

            if not summary_only:
                lead_data.append({
                    **_serialize_lead(lead, effectively_quoted),
                    "quotes": [_serialize_quote(q) for q in lead_quotes],
                    "is_bundled": is_bundled,
                    "product_lines": sorted(product_names),
                    "total_premium": sum(q.premium or 0 for q in lead_quotes),
                })
        elif effectively_quoted:
            # Lead has quote_date but no quote records (quoting happened but wasn't entered as structured data)
            quote_date_only += 1
            if not bundled_only and not summary_only:
                lead_data.append({
                    **_serialize_lead(lead, effectively_quoted),
                    "quotes": [],
                    "is_bundled": False,
                    "product_lines": [],
                    "total_premium": 0,
                })

    total_with_records = bundled_count + mono_count
    total_effectively_quoted = total_with_records + quote_date_only
    response = {
        "summary": {
            "total_effectively_quoted": total_effectively_quoted,
            "with_quote_records": total_with_records,
            "quote_date_only": quote_date_only,
            "bundled": bundled_count,
            "mono_line": mono_count,
            "bundle_rate_pct": f"{round(bundled_count / total_with_records * 100, 1) if total_with_records > 0 else 0}%",
            "by_carrier": sorted(carrier_counts.items(), key=lambda x: -x[1]),
            "by_product": sorted(product_counts.items(), key=lambda x: -x[1]),
        },
    }
    if not summary_only:
        response["leads"] = lead_data

    return response


# ---------------------------------------------------------------------------
# Funnel Performance
# ---------------------------------------------------------------------------

@router.get("/funnel-performance", dependencies=[Depends(verify_api_key)])
async def funnel_performance(
    producer: Optional[str] = Query(None, description="Filter by producer firstname"),
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline ID"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline name (partial match)"),
    lead_source: Optional[str] = Query(None, description="Filter by lead_source_name"),
    source_group: Optional[str] = Query(None, description="Filter by classified source group"),
    channel_type: Optional[str] = Query(None, description="Filter by channel type (internet, inbound, etc.)"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD (filters on enter_stage_date)"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    days: int = Query(30, description="Look back N days if date_from not set", ge=1, le=365),
    group_by: Optional[str] = Query(None, description="Group results: producer, pipeline, source, day, week"),
    report_mode: str = Query("standard", description="standard (rates from entered) or internet (rates from contacted/quoted)"),
    summary_only: bool = Query(True, description="Omit groups array (default true for safety)"),
    include_leads: bool = Query(False, description="Include per-lead detail (off by default)"),
):
    """Executive funnel metrics with flexible grouping and timing.

    Filters on enter_stage_date (when lead entered funnel), not last_activity_date.
    Use group_by to break down by producer, pipeline, source, day, or week.
    report_mode controls denominator logic for rates.
    """
    # Compute date range
    if date_from:
        start = date_from
    else:
        start = (_today_pacific() - timedelta(days=days - 1)).isoformat()
    end = (date_to or _today_pacific().isoformat()) + "T23:59:59"

    async with async_session() as session:
        # Build query filtering on create_date (when lead was created in AZ)
        # Falls back to enter_stage_date if create_date is not populated
        conditions = [
            or_(
                (Lead.create_date >= start) & (Lead.create_date <= end),
                (Lead.create_date == None) & (Lead.enter_stage_date >= start) & (Lead.enter_stage_date <= end),
            ),
        ]
        if producer:
            conditions.append(func.lower(Lead.assign_to_firstname) == producer.lower())
        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)
        if pipeline_name:
            conditions.append(Lead.workflow_name.ilike(f"%{pipeline_name}%"))
        if lead_source:
            conditions.append(Lead.lead_source_name == lead_source)

        query = select(Lead).where(*conditions)
        result = await session.execute(query)
        leads = result.scalars().all()

        # Post-filter by classification (computed in Python)
        if source_group:
            leads = [l for l in leads if classify_source(l.lead_source_name) == source_group]
        if channel_type:
            leads = [l for l in leads if classify_pipeline(l.workflow_name).get("channel_type") == channel_type]

        # Get quoted lead IDs and bundle info
        lead_ids = [l.id for l in leads]
        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()

        # Get bundle detection: lead_id -> number of distinct products
        bundled_ids = set()
        if lead_ids:
            bundle_q = (
                select(LeadQuote.lead_id, func.count(func.distinct(LeadQuote.product_name)))
                .where(LeadQuote.lead_id.in_(lead_ids), LeadQuote.product_name != None)
                .group_by(LeadQuote.lead_id)
            )
            bundle_result = await session.execute(bundle_q)
            bundled_ids = {row[0] for row in bundle_result if row[1] > 1}

            # Count products per quoted lead for avg_products metric
            products_q = (
                select(LeadQuote.lead_id, func.count(func.distinct(LeadQuote.product_name)))
                .where(LeadQuote.lead_id.in_(lead_ids), LeadQuote.product_name != None)
                .group_by(LeadQuote.lead_id)
            )
            products_result = await session.execute(products_q)
            products_per_lead = {row[0]: row[1] for row in products_result}
        else:
            products_per_lead = {}

        # Load name maps for serialization
        pipelines_map, stages_map = await _load_name_maps(session)

    def _compute_group_metrics(group_leads: list) -> dict:
        """Compute funnel metrics for a group of leads."""
        entered = len(group_leads)
        contacted = sum(1 for l in group_leads if l.contact_date)
        quoted = sum(1 for l in group_leads if _is_effectively_quoted(l, quoted_lead_ids))
        won = sum(1 for l in group_leads if l.status == 2)
        lost = sum(1 for l in group_leads if l.status == 3)
        expired = sum(1 for l in group_leads if l.status == 5)
        bundled = sum(1 for l in group_leads if l.id in bundled_ids)
        mono = sum(1 for l in group_leads if _is_effectively_quoted(l, quoted_lead_ids) and l.id not in bundled_ids)

        # Product counts for avg_products_per_quoted_lead
        quoted_product_counts = [products_per_lead.get(l.id, 0) for l in group_leads if _is_effectively_quoted(l, quoted_lead_ids)]
        avg_products = round(sum(quoted_product_counts) / len(quoted_product_counts), 1) if quoted_product_counts else 0

        # Rate calculations depend on report_mode
        if report_mode == "internet":
            quote_rate = round(quoted / contacted, 3) if contacted > 0 else 0
            close_rate_primary = round(won / quoted, 3) if quoted > 0 else 0
        else:
            quote_rate = round(quoted / entered, 3) if entered > 0 else 0
            close_rate_primary = round(won / entered, 3) if entered > 0 else 0

        close_rate_entered = round(won / entered, 3) if entered > 0 else 0
        close_rate_quoted = round(won / quoted, 3) if quoted > 0 else 0

        # Timing metrics
        speed_to_contact = [_hours_between(l.enter_stage_date, l.contact_date) for l in group_leads]
        speed_to_quote = [_hours_between(l.contact_date, l.quote_date) for l in group_leads]
        created_to_quote = [_hours_between(l.enter_stage_date, l.quote_date) for l in group_leads]
        quote_to_bind = [_hours_between(l.quote_date, l.sold_date) for l in group_leads]

        return {
            "leads_entered": entered,
            "contacted": contacted,
            "quoted_leads": quoted,
            "won": won,
            "lost": lost,
            "expired": expired,
            "active": entered - won - lost - expired,
            "quote_rate_pct": f"{quote_rate * 100:.1f}%",
            "close_rate_entered_pct": f"{close_rate_entered * 100:.1f}%",
            "close_rate_quoted_pct": f"{close_rate_quoted * 100:.1f}%",
            "bundled": bundled,
            "mono_line": mono,
            "bundle_rate_pct": f"{round(bundled / quoted * 100, 1) if quoted > 0 else 0}%",
            "avg_products_per_quoted_lead": avg_products,
            "timing": {
                "speed_to_contact": _timing_stats(speed_to_contact),
                "speed_to_quote": _timing_stats(speed_to_quote),
                "created_to_quote": _timing_stats(created_to_quote),
                "quote_to_bind": _timing_stats(quote_to_bind),
            },
        }

    # Compute overall summary
    summary = _compute_group_metrics(leads)

    response = {
        "date_range": {"from": start, "to": date_to or _today_pacific().isoformat()},
        "filters": {
            "producer": producer,
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline_name,
            "lead_source": lead_source,
            "source_group": source_group,
            "channel_type": channel_type,
            "report_mode": report_mode,
        },
        "summary": summary,
    }

    # Group breakdowns
    if not summary_only and group_by:
        def _group_key(lead):
            if group_by == "producer":
                return lead.assign_to_firstname or "Unknown"
            elif group_by == "pipeline":
                return lead.workflow_name or pipelines_map.get(lead.pipeline_id, "Unknown")
            elif group_by == "source":
                return lead.lead_source_name or "Unknown"
            elif group_by == "day":
                return (lead.enter_stage_date or "")[:10] or "Unknown"
            elif group_by == "week":
                dt = _parse_date_str(lead.enter_stage_date)
                if dt:
                    # ISO week: YYYY-Www
                    return f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
                return "Unknown"
            return "all"

        groups = {}
        for lead in leads:
            key = _group_key(lead)
            groups.setdefault(key, []).append(lead)

        group_results = []
        for key, group_leads in sorted(groups.items()):
            metrics = _compute_group_metrics(group_leads)
            metrics["key"] = key
            # Add classification for pipeline groups
            if group_by == "pipeline":
                classification = classify_pipeline(key)
                metrics["channel_type"] = classification["channel_type"]
                metrics["intent_type"] = classification["intent_type"]
            elif group_by == "source":
                metrics["source_group"] = classify_source(key)
            group_results.append(metrics)

        # Sort by leads_entered descending for readability
        group_results.sort(key=lambda x: -x["leads_entered"])
        response["groups"] = group_results

    # Per-lead detail (off by default)
    if include_leads:
        response["leads"] = [
            {
                **_serialize_lead(l, _is_effectively_quoted(l, quoted_lead_ids), pipelines_map, stages_map),
                "is_bundled": l.id in bundled_ids,
                "channel_type": classify_pipeline(l.workflow_name or pipelines_map.get(l.pipeline_id)).get("channel_type"),
                "intent_type": classify_pipeline(l.workflow_name or pipelines_map.get(l.pipeline_id)).get("intent_type"),
                "source_group": classify_source(l.lead_source_name),
            }
            for l in leads
        ]

    return response


@router.get("/data-quality", dependencies=[Depends(verify_api_key)])
async def data_quality_report(
    producer: Optional[str] = Query(None, description="Filter by producer firstname"),
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline ID"),
    days: int = Query(90, description="How far back to scan", ge=1, le=365),
):
    """Data quality diagnostics — surfaces pipeline discipline issues and missing data.

    Scans leads for common data quality problems like quoted leads with wrong status,
    missing timestamps, stuck leads, and timeline anomalies.
    """
    start = (_today_pacific() - timedelta(days=days - 1)).isoformat()

    async with async_session() as session:
        conditions = [Lead.last_activity_date >= start]
        if producer:
            conditions.append(func.lower(Lead.assign_to_firstname) == producer.lower())
        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)

        result = await session.execute(select(Lead).where(*conditions))
        leads = result.scalars().all()
        lead_ids = [l.id for l in leads]

        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()

    today = _today_pacific()

    def _days_old(date_str):
        dt = _parse_date_str(date_str)
        if not dt:
            return None
        return (datetime.combine(today, datetime.min.time()) - dt).days

    # Diagnostic categories
    issues = {}

    # 1. Quoted but wrong status (has quotes but status is NEW or CONTACTED)
    quoted_wrong = [l for l in leads if _is_effectively_quoted(l, quoted_lead_ids) and l.status in (0, 4)]
    issues["quoted_but_wrong_status"] = {
        "count": len(quoted_wrong),
        "severity": "high",
        "description": "Has quote records or quote_date but status is NEW or CONTACTED",
    }

    # 2. Won without quote (status=WON but no quote records and no quote_date)
    won_no_quote = [l for l in leads if l.status == 2 and not _is_effectively_quoted(l, quoted_lead_ids)]
    issues["won_without_quote"] = {
        "count": len(won_no_quote),
        "severity": "medium",
        "description": "Status is WON but no quote records or quote_date found",
    }

    # 3. Expired with quote (status=EXPIRED but has quote records)
    expired_quoted = [l for l in leads if l.status == 5 and _is_effectively_quoted(l, quoted_lead_ids)]
    issues["expired_with_quote"] = {
        "count": len(expired_quoted),
        "severity": "medium",
        "description": "Status is EXPIRED but has quote records (potential lost revenue)",
    }

    # 4. Missing contact date (contacted/quoted/won but no contact_date)
    missing_contact = [l for l in leads if (l.status in (4,) or _is_effectively_quoted(l, quoted_lead_ids) or l.status == 2) and not l.contact_date]
    issues["missing_contact_date"] = {
        "count": len(missing_contact),
        "severity": "low",
        "description": "Lead is contacted/quoted/won but contact_date is not set",
    }

    # 5. Missing quote date (has quote records but quote_date field is null)
    missing_quote_date = [l for l in leads if l.id in quoted_lead_ids and not l.quote_date]
    issues["missing_quote_date"] = {
        "count": len(missing_quote_date),
        "severity": "low",
        "description": "Has quote records but quote_date field is not set on lead",
    }

    # 6. Stuck leads (status=NEW for 14+ days)
    stuck = [l for l in leads if l.status == 0 and not _is_effectively_quoted(l, quoted_lead_ids)]
    stuck = [l for l in stuck if _days_old(l.enter_stage_date) is not None and _days_old(l.enter_stage_date) > 14]
    issues["stuck_in_new_14_plus_days"] = {
        "count": len(stuck),
        "severity": "high",
        "description": "Status is NEW (not quoted) and has been in current stage for 14+ days",
    }

    # 7. Sold without sold_date
    sold_no_date = [l for l in leads if l.status == 2 and not l.sold_date]
    issues["sold_without_sold_date"] = {
        "count": len(sold_no_date),
        "severity": "medium",
        "description": "Status is WON but sold_date is not recorded",
    }

    # 8. Timeline anomalies (dates out of logical order)
    timeline_bad = []
    for l in leads:
        sold_dt = _parse_date_str(l.sold_date)
        quote_dt = _parse_date_str(l.quote_date)
        contact_dt = _parse_date_str(l.contact_date)
        if sold_dt and quote_dt and sold_dt < quote_dt:
            timeline_bad.append(l)
        elif quote_dt and contact_dt and quote_dt < contact_dt:
            timeline_bad.append(l)
    issues["timeline_anomalies"] = {
        "count": len(timeline_bad),
        "severity": "low",
        "description": "Dates are out of logical order (e.g., sold before quoted)",
    }

    # Total issues
    total_issues = sum(issue["count"] for issue in issues.values())
    total_leads = len(leads)
    health_score = round((total_leads - total_issues) / total_leads * 100) if total_leads > 0 else 100

    # Sample leads per category (up to 5 each)
    sample_leads = {}
    category_leads = {
        "quoted_but_wrong_status": quoted_wrong,
        "won_without_quote": won_no_quote,
        "expired_with_quote": expired_quoted,
        "stuck_in_new_14_plus_days": stuck,
        "sold_without_sold_date": sold_no_date,
        "timeline_anomalies": timeline_bad,
    }
    for cat, cat_leads in category_leads.items():
        if cat_leads:
            sample_leads[cat] = [
                {"id": l.id, "name": f"{l.firstname or ''} {l.lastname or ''}".strip(),
                 "status": STATUS_MAP.get(l.status, "unknown"), "producer": l.assign_to_firstname,
                 "pipeline": l.workflow_name, "enter_stage_date": l.enter_stage_date}
                for l in cat_leads[:5]
            ]

    return {
        "date_range": {"from": start, "to": _today_pacific().isoformat()},
        "total_leads_scanned": total_leads,
        "total_issues": total_issues,
        "health_score_pct": f"{health_score}%",
        "issues": issues,
        "sample_leads": sample_leads,
    }


# ---------------------------------------------------------------------------
# Pipeline Compliance
# ---------------------------------------------------------------------------

@router.get("/pipeline-compliance", dependencies=[Depends(verify_api_key)])
async def pipeline_compliance(
    producer: Optional[str] = Query(None, description="Filter by producer firstname"),
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline ID"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline name (partial match)"),
    date_from: str = Query(..., description="Start date YYYY-MM-DD (filters on enter_stage_date)"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
    summary_only: bool = Query(True, description="Omit unquoted leads list (default true)"),
):
    """Quote compliance and SLA metrics for a pipeline scope.

    Returns quote rate, compliance status (passing/warning/failing based on pipeline
    intent type), timing metrics, and optionally the list of unquoted leads.
    """
    end = date_to + "T23:59:59"

    async with async_session() as session:
        conditions = [
            Lead.enter_stage_date >= date_from,
            Lead.enter_stage_date <= end,
        ]
        if producer:
            conditions.append(func.lower(Lead.assign_to_firstname) == producer.lower())
        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)
        if pipeline_name:
            conditions.append(Lead.workflow_name.ilike(f"%{pipeline_name}%"))

        result = await session.execute(select(Lead).where(*conditions))
        leads = result.scalars().all()
        lead_ids = [l.id for l in leads]

        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()
        pipelines_map, stages_map = await _load_name_maps(session)

    # Determine pipeline for compliance thresholds
    pipeline_names_seen = set(l.workflow_name or pipelines_map.get(l.pipeline_id, "Unknown") for l in leads)
    primary_pipeline = pipeline_names_seen.pop() if len(pipeline_names_seen) == 1 else None
    intent = classify_pipeline(primary_pipeline).get("intent_type", "other") if primary_pipeline else "other"

    # Classify leads
    total = len(leads)
    quoted_leads = [l for l in leads if _is_effectively_quoted(l, quoted_lead_ids)]
    unquoted_leads = [l for l in leads if not _is_effectively_quoted(l, quoted_lead_ids)]
    quoted = len(quoted_leads)
    not_quoted = len(unquoted_leads)

    quote_rate = quoted / total if total > 0 else 0

    # Timing for quoted leads
    time_to_quote = [_hours_between(l.enter_stage_date, l.quote_date) for l in quoted_leads]

    # Same-day quotes
    same_day = 0
    quoted_after_24h = 0
    for l in quoted_leads:
        hours = _hours_between(l.enter_stage_date, l.quote_date)
        if hours is not None:
            if hours <= 24:
                entered_day = (l.enter_stage_date or "")[:10]
                quoted_day = (l.quote_date or "")[:10]
                if entered_day and quoted_day and entered_day == quoted_day:
                    same_day += 1
            if hours > 24:
                quoted_after_24h += 1

    # No quote, no disposition — we don't have disposition_reason from AZ
    # so all unquoted leads count here
    no_quote_no_disposition = not_quoted

    compliance_status = get_compliance_status(quote_rate, intent)
    timing = _timing_stats(time_to_quote)

    source_notes = []
    if not primary_pipeline:
        source_notes.append("Multiple pipelines in scope — compliance threshold uses 'other' defaults")
    source_notes.append("disposition_reason not available from AgencyZoom API — all unquoted leads counted as no_quote_no_disposition")

    summary = {
        "total_leads": total,
        "quoted": quoted,
        "not_quoted": not_quoted,
        "quote_rate_pct": f"{round(quote_rate * 100, 1)}%",
        "same_day_quote_pct": f"{round(same_day / total * 100, 1) if total > 0 else 0}%",
        "avg_time_to_quote_hours": timing["avg_hours"],
        "median_time_to_quote_hours": timing["median_hours"],
        "quoted_after_24h": quoted_after_24h,
        "no_quote_no_disposition": no_quote_no_disposition,
        "compliance_status": compliance_status,
        "pipeline_intent_type": intent,
    }

    response = {
        "date_range": {"from": date_from, "to": date_to},
        "scope": {
            "producer": producer,
            "pipeline_id": pipeline_id,
            "pipeline_name": primary_pipeline or pipeline_name,
        },
        "summary": summary,
        "source_notes": source_notes,
    }

    if not summary_only:
        response["unquoted_leads"] = [
            {
                "lead_id": l.id,
                "name": f"{l.firstname or ''} {l.lastname or ''}".strip(),
                "pipeline_name": l.workflow_name or pipelines_map.get(l.pipeline_id),
                "status": STATUS_MAP.get(l.status, "unknown"),
                "stage": l.workflow_stage_name or stages_map.get(l.stage_id),
                "lead_source": l.lead_source_name,
                "created_at": l.enter_stage_date,
                "last_activity_at": l.last_activity_date,
            }
            for l in unquoted_leads
        ]
    else:
        response["unquoted_leads"] = []

    return response


# ---------------------------------------------------------------------------
# Lost Deal Analysis
# ---------------------------------------------------------------------------

@router.get("/lost-deal-analysis", dependencies=[Depends(verify_api_key)])
async def lost_deal_analysis(
    producer: Optional[str] = Query(None, description="Filter by producer firstname"),
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline ID"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline name (partial match)"),
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
    include_recoverable: bool = Query(True, description="Include recoverable lead list"),
    summary_only: bool = Query(True, description="Omit per-lead detail lists"),
):
    """Audit quoted leads that did not close. Identifies post-quote leakage and recoverable opportunities."""
    end = date_to + "T23:59:59"

    async with async_session() as session:
        # Get all leads in scope
        conditions = [
            Lead.last_activity_date >= date_from,
            Lead.last_activity_date <= end,
        ]
        if producer:
            conditions.append(func.lower(Lead.assign_to_firstname) == producer.lower())
        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)
        if pipeline_name:
            conditions.append(Lead.workflow_name.ilike(f"%{pipeline_name}%"))

        result = await session.execute(select(Lead).where(*conditions))
        leads = result.scalars().all()
        lead_ids = [l.id for l in leads]

        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()
        pipelines_map, stages_map = await _load_name_maps(session)

    # Filter to effectively quoted leads only
    quoted_leads = [l for l in leads if _is_effectively_quoted(l, quoted_lead_ids)]
    quoted = len(quoted_leads)
    won = sum(1 for l in quoted_leads if l.status == 2)
    lost = sum(1 for l in quoted_leads if l.status == 3)
    expired = sum(1 for l in quoted_leads if l.status == 5)
    still_open = quoted - won - lost - expired

    close_rate = round(won / quoted, 3) if quoted > 0 else 0
    leakage = lost + expired
    post_quote_leakage = round(leakage / quoted, 3) if quoted > 0 else 0

    # Failure reasons — group by status since we don't have disposition_reason
    failure_reasons = {}
    for l in quoted_leads:
        if l.status in (3, 5):  # lost or expired
            status_name = STATUS_MAP.get(l.status, "unknown")
            failure_reasons[status_name] = failure_reasons.get(status_name, 0) + 1

    # Recoverable leads: quoted, not won, not expired too long ago, status is NEW/CONTACTED/LOST
    recoverable = []
    if include_recoverable:
        today = _today_pacific()
        for l in quoted_leads:
            if l.status == 2:  # already won
                continue
            # Consider recoverable if last activity within 60 days
            days_since = None
            dt = _parse_date_str(l.last_activity_date)
            if dt:
                days_since = (datetime.combine(today, datetime.min.time()) - dt).days
            if days_since is not None and days_since <= 60:
                recoverable.append(l)

    source_notes = [
        "disposition_reason not available from AZ API — failure_reasons grouped by status only",
        "follow_up_count_after_quote not available — notes are not synced; would require live API calls",
        "Recoverable heuristic: quoted + not won + last activity within 60 days",
    ]

    def _lead_lite(l):
        return {
            "lead_id": l.id,
            "name": f"{l.firstname or ''} {l.lastname or ''}".strip(),
            "pipeline_name": l.workflow_name or pipelines_map.get(l.pipeline_id),
            "status": STATUS_MAP.get(l.status, "unknown"),
            "lead_source": l.lead_source_name,
            "created_at": l.enter_stage_date,
            "quoted_at": l.quote_date,
            "sold_at": l.sold_date,
            "last_activity_at": l.last_activity_date,
            "time_to_quote_hours": _hours_between(l.enter_stage_date, l.quote_date),
        }

    response = {
        "date_range": {"from": date_from, "to": date_to},
        "scope": {
            "producer": producer,
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline_name,
        },
        "summary": {
            "quoted": quoted,
            "won": won,
            "lost": lost,
            "expired": expired,
            "still_open": still_open,
            "close_rate_pct": f"{close_rate * 100:.1f}%",
            "post_quote_leakage_pct": f"{post_quote_leakage * 100:.1f}%",
            "recoverable_count": len(recoverable),
            "avg_follow_up_count_after_quote": None,
            "no_follow_up_after_quote_pct": None,
        },
        "failure_reasons": failure_reasons,
        "source_notes": source_notes,
    }

    if not summary_only:
        lost_expired = [l for l in quoted_leads if l.status in (3, 5)]
        response["lost_or_expired_quoted_leads"] = [_lead_lite(l) for l in lost_expired]
        response["recoverable_leads"] = [_lead_lite(l) for l in recoverable]
    else:
        response["lost_or_expired_quoted_leads"] = []
        response["recoverable_leads"] = []

    return response


# ---------------------------------------------------------------------------
# Producer Scorecard
# ---------------------------------------------------------------------------

@router.get("/producer-scorecard", dependencies=[Depends(verify_api_key)])
async def producer_scorecard(
    producer: str = Query(..., description="Producer firstname"),
    date_from: str = Query(..., description="Start date YYYY-MM-DD"),
    date_to: str = Query(..., description="End date YYYY-MM-DD"),
):
    """One-response KPI summary for a producer across all pipelines with team rankings."""
    end = date_to + "T23:59:59"

    async with async_session() as session:
        # Get this producer's leads
        result = await session.execute(
            select(Lead).where(
                func.lower(Lead.assign_to_firstname) == producer.lower(),
                Lead.enter_stage_date >= date_from,
                Lead.enter_stage_date <= end,
            )
        )
        leads = result.scalars().all()
        lead_ids = [l.id for l in leads]

        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids) if lead_ids else set()
        pipelines_map, _ = await _load_name_maps(session)

        # Get ALL producers' leads for ranking
        all_result = await session.execute(
            select(Lead).where(
                Lead.enter_stage_date >= date_from,
                Lead.enter_stage_date <= end,
            )
        )
        all_leads = all_result.scalars().all()
        all_lead_ids = [l.id for l in all_leads]
        all_quoted_ids = await _get_quoted_lead_ids(session, all_lead_ids) if all_lead_ids else set()

        # Get active producers
        emp_result = await session.execute(
            select(Employee).where(Employee.is_producer == 1, Employee.is_active == 1)
        )
        all_producers = emp_result.scalars().all()

    # Helper to compute metrics for a set of leads
    def _compute_kpis(lead_set, q_ids):
        total = len(lead_set)
        quoted = sum(1 for l in lead_set if _is_effectively_quoted(l, q_ids))
        won = sum(1 for l in lead_set if l.status == 2)
        lost = sum(1 for l in lead_set if l.status == 3)
        expired = sum(1 for l in lead_set if l.status == 5)

        # Leakage
        terminal_unquoted = sum(1 for l in lead_set if l.status in (3, 5) and not _is_effectively_quoted(l, q_ids))
        quoted_terminal = sum(1 for l in lead_set if l.status in (3, 5) and _is_effectively_quoted(l, q_ids))

        quote_rate = round(quoted / total, 3) if total > 0 else 0
        close_rate = round(won / quoted, 3) if quoted > 0 else 0
        pre_leak = round(terminal_unquoted / total, 3) if total > 0 else 0
        post_leak = round(quoted_terminal / quoted, 3) if quoted > 0 else 0

        time_to_quote = [_hours_between(l.enter_stage_date, l.quote_date) for l in lead_set if _is_effectively_quoted(l, q_ids)]
        timing = _timing_stats(time_to_quote)

        return {
            "new_leads": total,
            "quoted": quoted,
            "won": won,
            "lost": lost,
            "expired": expired,
            "quote_rate_pct": f"{quote_rate * 100:.1f}%",
            "close_rate_pct": f"{close_rate * 100:.1f}%",
            "pre_quote_leakage_pct": f"{pre_leak * 100:.1f}%",
            "post_quote_leakage_pct": f"{post_leak * 100:.1f}%",
            "avg_time_to_quote_hours": timing["avg_hours"],
            "_quote_rate": quote_rate,
            "_close_rate": close_rate,
            "_lead_to_close": round(won / total, 3) if total > 0 else 0,
        }

    # This producer's KPIs
    kpis = _compute_kpis(leads, quoted_lead_ids)

    # Pipeline breakdown
    by_pipeline = {}
    for l in leads:
        pname = l.workflow_name or pipelines_map.get(l.pipeline_id, "Unknown")
        by_pipeline.setdefault(pname, []).append(l)

    pipeline_breakdown = []
    for pname, p_leads in sorted(by_pipeline.items(), key=lambda x: -len(x[1])):
        p_kpis = _compute_kpis(p_leads, quoted_lead_ids)
        pipeline_breakdown.append({
            "pipeline_name": pname,
            "leads": len(p_leads),
            "quote_rate_pct": p_kpis["quote_rate_pct"],
            "close_rate_pct": p_kpis["close_rate_pct"],
            "pre_quote_leakage_pct": p_kpis["pre_quote_leakage_pct"],
            "post_quote_leakage_pct": p_kpis["post_quote_leakage_pct"],
        })

    # Rankings: compute KPIs for all producers and rank
    producer_kpis = {}
    producer_map = {p.id: p for p in all_producers}
    for l in all_leads:
        pid = l.assigned_to
        if pid not in producer_kpis:
            producer_kpis[pid] = []
        producer_kpis[pid].append(l)

    rankings_data = []
    for pid, p_leads in producer_kpis.items():
        prod = producer_map.get(pid)
        name = prod.firstname if prod else str(pid)
        pk = _compute_kpis(p_leads, all_quoted_ids)
        rankings_data.append({
            "name": name,
            "quote_rate": pk["_quote_rate"],
            "close_rate": pk["_close_rate"],
            "lead_to_close": pk["_lead_to_close"],
        })

    # Sort and rank
    by_qr = sorted(rankings_data, key=lambda x: -x["quote_rate"])
    by_cr = sorted(rankings_data, key=lambda x: -x["close_rate"])
    by_ltc = sorted(rankings_data, key=lambda x: -x["lead_to_close"])

    def _find_rank(sorted_list, producer_name):
        for i, item in enumerate(sorted_list):
            if item["name"].lower() == producer_name.lower():
                return i + 1
        return None

    # Find employee name for matching
    emp_match = None
    for p in all_producers:
        if p.firstname and p.firstname.lower() == producer.lower():
            emp_match = p
            break

    producer_display = emp_match.firstname if emp_match else producer

    rankings = {
        "quote_rate_rank": _find_rank(by_qr, producer_display),
        "close_rate_rank": _find_rank(by_cr, producer_display),
        "lead_to_close_rank": _find_rank(by_ltc, producer_display),
        "total_producers": len(rankings_data),
    }

    # Clean internal fields from kpis
    del kpis["_quote_rate"]
    del kpis["_close_rate"]
    del kpis["_lead_to_close"]

    return {
        "producer": producer_display,
        "date_range": {"from": date_from, "to": date_to},
        "kpis": kpis,
        "rankings": rankings,
        "pipeline_breakdown": pipeline_breakdown,
        "source_notes": [
            "pre_quote_leakage = leads that reached terminal status (lost/expired) without being quoted",
            "post_quote_leakage = quoted leads that reached terminal status without winning",
            "Rankings computed against all active producers in the same date range",
        ],
    }


# ---------------------------------------------------------------------------
# Coaching Analysis
# ---------------------------------------------------------------------------

def _strip_html(text: str | None) -> str:
    """Strip HTML tags from note body for cleaner LLM consumption."""
    if not text:
        return ""
    import re
    clean = re.sub(r'<[^>]+>', ' ', text)
    return ' '.join(clean.split())[:500]  # cap at 500 chars


@router.get("/coaching-analysis", dependencies=[Depends(verify_api_key)])
async def coaching_analysis(
    producer: str = Query(..., description="Producer firstname"),
    date_from: Optional[str] = Query(None, description="Start date YYYY-MM-DD (defaults to yesterday)"),
    date_to: Optional[str] = Query(None, description="End date YYYY-MM-DD (defaults to date_from)"),
    days: int = Query(1, description="Look back N days if date_from not set", ge=1, le=30),
    include_note_content: bool = Query(True, description="Include note body text (for LLM analysis)"),
    max_notes_per_lead: int = Query(10, description="Cap notes per lead to control response size", ge=1, le=100),
    summary_only: bool = Query(False, description="Return only summary and coaching flags, omit per-lead detail"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline name (partial match)"),
    pipeline_id: Optional[str] = Query(None, description="Filter by pipeline ID"),
):
    """Coaching analysis for a producer — surfaces communication patterns, follow-up gaps, and opportunities.

    Returns per-lead activity breakdown with notes, tasks, timing, and coaching flags.
    Use summary_only=true for high-volume producers to avoid oversized responses.
    Designed for LLM consumption to generate coaching feedback.
    """
    # Compute date range
    if date_from:
        start = date_from
    else:
        start = (_today_pacific() - timedelta(days=days)).isoformat()
    if date_to:
        end = date_to
    else:
        end = date_from if date_from else (_today_pacific() - timedelta(days=1)).isoformat()
    end_ts = end + "T23:59:59"

    async with async_session() as session:
        # Get leads with activity in the date range for this producer
        conditions = [
            func.lower(Lead.assign_to_firstname) == producer.lower(),
            Lead.last_activity_date >= start,
            Lead.last_activity_date <= end_ts,
        ]
        if pipeline_name:
            conditions.append(Lead.workflow_name.ilike(f"%{pipeline_name}%"))
        if pipeline_id:
            conditions.append(Lead.pipeline_id == pipeline_id)

        lead_result = await session.execute(
            select(Lead).where(*conditions).order_by(Lead.last_activity_date.desc())
        )
        leads = lead_result.scalars().all()
        lead_ids = [l.id for l in leads]

        if not lead_ids:
            return {
                "producer": producer,
                "date_range": {"from": start, "to": end},
                "summary": {"leads_active": 0},
                "leads": [],
                "coaching_flags": [],
            }

        # Get quoted lead IDs
        quoted_lead_ids = await _get_quoted_lead_ids(session, lead_ids)

        # Get all notes for these leads in the date range
        notes_result = await session.execute(
            select(LeadNote).where(
                LeadNote.lead_id.in_(lead_ids),
            ).order_by(LeadNote.create_date.asc())
        )
        all_notes = notes_result.scalars().all()

        # Get all tasks for these leads
        tasks_result = await session.execute(
            select(LeadTask).where(LeadTask.lead_id.in_(lead_ids))
        )
        all_tasks = tasks_result.scalars().all()

        # Load name maps
        pipelines_map, stages_map = await _load_name_maps(session)

    # Group notes and tasks by lead
    notes_by_lead = {}
    for n in all_notes:
        notes_by_lead.setdefault(n.lead_id, []).append(n)

    tasks_by_lead = {}
    for t in all_tasks:
        tasks_by_lead.setdefault(t.lead_id, []).append(t)

    # Analyze each lead
    lead_analyses = []
    coaching_flags = []

    # Aggregate counters
    total_emails = 0
    total_texts = 0
    total_calls = 0
    total_tasks_count = 0
    leads_with_no_notes = 0
    leads_with_no_contact = 0
    leads_quoted_no_followup = 0
    leads_missing_tasks = 0

    for lead in leads:
        lead_notes = notes_by_lead.get(lead.id, [])
        lead_tasks = tasks_by_lead.get(lead.id, [])
        is_quoted = _is_effectively_quoted(lead, quoted_lead_ids)

        # Filter notes to the date range for activity counting
        notes_in_range = [n for n in lead_notes if n.create_date and n.create_date >= start and n.create_date <= end_ts]

        # Count by type — period only (not lifetime)
        period_type_counts = {}
        for n in notes_in_range:
            t = n.note_type or "unknown"
            period_type_counts[t] = period_type_counts.get(t, 0) + 1

        emails_period = period_type_counts.get("EMAIL", 0)
        texts_period = period_type_counts.get("TEXT", 0)
        calls_period = period_type_counts.get("comment", 0)  # call logs are stored as "comment" type
        stage_moves_period = period_type_counts.get("MOVE_STAGE", 0)

        # Lifetime counts for reference
        lifetime_type_counts = {}
        for n in lead_notes:
            t = n.note_type or "unknown"
            lifetime_type_counts[t] = lifetime_type_counts.get(t, 0) + 1

        total_emails += emails_period
        total_texts += texts_period
        total_calls += calls_period
        total_tasks_count += len(lead_tasks)

        # Timing
        hours_to_contact = _hours_between(lead.enter_stage_date, lead.contact_date)
        hours_to_quote = _hours_between(lead.enter_stage_date, lead.quote_date)

        # Open tasks
        open_tasks = [t for t in lead_tasks if t.status and t.status.lower() not in ("completed", "done")]
        overdue_tasks = []
        today = _today_pacific()
        for t in open_tasks:
            if t.due_date:
                due = _parse_date_str(t.due_date)
                if due and due.date() < today:
                    overdue_tasks.append(t)

        # Coaching flags for this lead
        lead_flags = []

        if not lead_notes:
            leads_with_no_notes += 1
            lead_flags.append("no_notes_at_all")

        if not lead.contact_date and lead.status == 0:
            leads_with_no_contact += 1
            lead_flags.append("new_lead_never_contacted")

        if not notes_in_range and lead_notes:
            lead_flags.append("no_activity_in_period")

        if is_quoted and lead.status not in (2, 3, 5):
            # Quoted but still open — check for follow-up after quote
            post_quote_notes = [n for n in lead_notes if n.create_date and lead.quote_date and n.create_date > lead.quote_date]
            if not post_quote_notes:
                leads_quoted_no_followup += 1
                lead_flags.append("quoted_no_followup")

        if overdue_tasks:
            lead_flags.append(f"overdue_tasks_{len(overdue_tasks)}")

        if not lead_tasks:
            leads_missing_tasks += 1
            lead_flags.append("missing_tasks")

        if hours_to_contact and hours_to_contact > 24:
            lead_flags.append("slow_first_contact")

        # Build note timeline (capped)
        note_timeline = []
        for n in lead_notes[:max_notes_per_lead]:
            entry = {
                "type": n.note_type,
                "date": n.create_date,
                "title": n.title,
            }
            if include_note_content:
                entry["body"] = _strip_html(n.body)
            note_timeline.append(entry)

        # Build task list
        task_list = [
            {
                "title": t.title,
                "status": t.status,
                "due_date": t.due_date,
                "type": t.task_type,
            }
            for t in lead_tasks
        ]

        pipeline_name = lead.workflow_name or pipelines_map.get(lead.pipeline_id)
        stage_name = lead.workflow_stage_name or stages_map.get(lead.stage_id)

        lead_analyses.append({
            "lead_id": lead.id,
            "name": f"{lead.firstname or ''} {lead.lastname or ''}".strip(),
            "pipeline": pipeline_name,
            "stage": stage_name,
            "status": STATUS_MAP.get(lead.status, "unknown"),
            "lead_source": lead.lead_source_name,
            "effectively_quoted": is_quoted,
            "enter_stage_date": lead.enter_stage_date,
            "contact_date": lead.contact_date,
            "quote_date": lead.quote_date,
            "last_activity": lead.last_activity_date,
            "hours_to_first_contact": hours_to_contact,
            "hours_to_quote": hours_to_quote,
            "activity_counts": {
                "notes_in_period": len(notes_in_range),
                "emails_in_period": emails_period,
                "texts_in_period": texts_period,
                "calls_in_period": calls_period,
                "stage_moves_in_period": stage_moves_period,
                "total_notes_lifetime": len(lead_notes),
                "emails_lifetime": lifetime_type_counts.get("EMAIL", 0),
                "texts_lifetime": lifetime_type_counts.get("TEXT", 0),
                "calls_lifetime": lifetime_type_counts.get("comment", 0),
                "tasks": len(lead_tasks),
                "open_tasks": len(open_tasks),
                "overdue_tasks": len(overdue_tasks),
            },
            "coaching_flags": lead_flags,
            "notes": note_timeline,
            "tasks": task_list,
        })

        if lead_flags:
            for flag in lead_flags:
                coaching_flags.append({
                    "flag": flag,
                    "lead_id": lead.id,
                    "lead_name": f"{lead.firstname or ''} {lead.lastname or ''}".strip(),
                    "pipeline": pipeline_name,
                })

    # Group coaching flags by type
    flag_summary = {}
    for cf in coaching_flags:
        flag_summary[cf["flag"]] = flag_summary.get(cf["flag"], 0) + 1

    return {
        "producer": producer,
        "date_range": {"from": start, "to": end},
        "summary": {
            "leads_active": len(leads),
            "leads_with_notes": len(leads) - leads_with_no_notes,
            "leads_no_notes": leads_with_no_notes,
            "leads_no_contact": leads_with_no_contact,
            "leads_quoted_no_followup": leads_quoted_no_followup,
            "leads_missing_tasks": leads_missing_tasks,
            "emails_in_period": total_emails,
            "texts_in_period": total_texts,
            "calls_in_period": total_calls,
            "total_tasks": total_tasks_count,
        },
        "coaching_flag_summary": flag_summary,
        "coaching_flags": coaching_flags if not summary_only else [],
        "leads": lead_analyses if not summary_only else [],
    }
