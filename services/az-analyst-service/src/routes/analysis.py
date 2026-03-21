"""Analysis REST API endpoints."""

import logging
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
from ..database import Employee, Lead, LeadFile, LeadQuote, Pipeline, Stage, async_session

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

STATUS_MAP = {0: "new", 1: "quoted", 2: "won", 3: "lost", 4: "contacted", 5: "expired"}


def _serialize_lead(lead: Lead) -> dict:
    """Convert a Lead ORM object to a JSON-serializable dict."""
    return {
        "id": lead.id,
        "name": f"{lead.firstname or ''} {lead.lastname or ''}".strip(),
        "firstname": lead.firstname,
        "lastname": lead.lastname,
        "pipeline": lead.workflow_name,
        "pipeline_id": lead.pipeline_id,
        "stage": lead.workflow_stage_name,
        "stage_id": lead.stage_id,
        "status": STATUS_MAP.get(lead.status, "unknown"),
        "status_code": lead.status,
        "last_activity": lead.last_activity_date,
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


def _today_pacific() -> date:
    """Get today's date in Pacific time."""
    return datetime.now(ZoneInfo(settings.az_timezone)).date()


@router.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@router.get("/producer-activity", dependencies=[Depends(verify_api_key)])
async def producer_activity(
    producer: str = Query(..., description="Producer firstname to match"),
    date: Optional[str] = Query(None, description="Date (YYYY-MM-DD), defaults to today Pacific"),
    days: int = Query(1, description="Look back N days", ge=1, le=90),
    include_details: bool = Query(False, description="Fetch notes/tasks from AZ API for top leads"),
):
    """Analyze a producer's lead activity for a given date range."""
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
        # Find producer info
        emp_result = await session.execute(
            select(Employee).where(
                func.lower(Employee.firstname) == producer.lower()
            )
        )
        employee = emp_result.scalar_one_or_none()

        # Query leads by producer firstname and activity date range
        query = select(Lead).where(
            func.lower(Lead.assign_to_firstname) == producer.lower(),
            Lead.last_activity_date >= start_date.isoformat(),
            Lead.last_activity_date <= end_date.isoformat() + "T23:59:59",
        ).order_by(Lead.last_activity_date.desc())

        result = await session.execute(query)
        leads = result.scalars().all()

        # Count by status
        status_counts = {"new": 0, "quoted": 0, "won": 0, "lost": 0, "contacted": 0, "expired": 0}
        for lead in leads:
            status_name = STATUS_MAP.get(lead.status, "unknown")
            if status_name in status_counts:
                status_counts[status_name] += 1

        # Group by pipeline
        pipeline_groups = {}
        for lead in leads:
            pname = lead.workflow_name or "Unknown"
            if pname not in pipeline_groups:
                pipeline_groups[pname] = {"name": pname, "active": 0}
            pipeline_groups[pname]["active"] += 1

        # Get total assigned per pipeline
        for pname in pipeline_groups:
            count_result = await session.execute(
                select(func.count(Lead.id)).where(
                    func.lower(Lead.assign_to_firstname) == producer.lower(),
                    Lead.workflow_name == pname,
                )
            )
            pipeline_groups[pname]["total_assigned"] = count_result.scalar() or 0

        # Serialize leads
        serialized_leads = [_serialize_lead(l) for l in leads]

        # Optionally fetch live details for top leads
        if include_details and leads:
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

    return {
        "producer": {
            "firstname": employee.firstname if employee else producer,
            "lastname": employee.lastname if employee else None,
            "id": employee.id if employee else None,
        },
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
        status_name = STATUS_MAP.get(lead.status, "unknown")
        if status_name in entry:
            entry[status_name] += 1

        # New lead breakdown
        if lead.status == 0:  # NEW
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
    bundled_only: bool = Query(False, description="Only show leads with multiple product lines"),
):
    """Analyze quoting patterns from synced quote data. No live AZ API calls."""
    async with async_session() as session:
        # Get all quoted/won leads with their quotes
        lead_query = select(Lead).where(Lead.status.in_([1, 2]))
        if producer:
            lead_query = lead_query.where(
                func.lower(Lead.assign_to_firstname) == producer.lower()
            )
        if pipeline_id:
            lead_query = lead_query.where(Lead.pipeline_id == pipeline_id)

        lead_result = await session.execute(lead_query)
        leads = lead_result.scalars().all()
        lead_ids = [l.id for l in leads]

        if not lead_ids:
            return {"leads": [], "summary": {"total": 0}}

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

    for lead in leads:
        lead_quotes = quotes_by_lead.get(lead.id, [])
        product_names = set(q.product_name for q in lead_quotes if q.product_name)
        is_bundled = len(product_names) > 1

        if bundled_only and not is_bundled:
            continue

        if is_bundled:
            bundled_count += 1
        elif lead_quotes:
            mono_count += 1

        for q in lead_quotes:
            if q.carrier_name:
                carrier_counts[q.carrier_name] = carrier_counts.get(q.carrier_name, 0) + 1
            if q.product_name:
                product_counts[q.product_name] = product_counts.get(q.product_name, 0) + 1

        lead_data.append({
            **_serialize_lead(lead),
            "quotes": [_serialize_quote(q) for q in lead_quotes],
            "is_bundled": is_bundled,
            "product_lines": sorted(product_names),
            "total_premium": sum(q.premium or 0 for q in lead_quotes),
        })

    return {
        "leads": lead_data,
        "summary": {
            "total": len(lead_data),
            "bundled": bundled_count,
            "mono_line": mono_count,
            "by_carrier": sorted(carrier_counts.items(), key=lambda x: -x[1]),
            "by_product": sorted(product_counts.items(), key=lambda x: -x[1]),
        },
    }
