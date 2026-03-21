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
from ..database import Employee, Lead, Pipeline, Stage, async_session

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
        "lead_type": lead.lead_type,
        "premium": lead.premium,
        "quoted": lead.quoted,
        "phone": lead.phone,
        "email": lead.email,
        "assigned_to": lead.assigned_to,
        "assign_to_firstname": lead.assign_to_firstname,
        "assign_to_lastname": lead.assign_to_lastname,
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
                top_leads = leads[:7]  # Cap at 7 leads (14 API calls)
                for i, lead in enumerate(top_leads):
                    try:
                        notes = await fetch_lead_notes(jwt, lead.id)
                        tasks = await fetch_lead_tasks(jwt, lead.id)
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
