"""Board routes: kanban board HTMX partials."""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import distinct, func, select

from ..auth import get_current_user
from ..database import Lead, Pipeline, Stage, async_session

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory="src/templates")


def _require_auth(request: Request, user):
    """Return redirect response if user is not authenticated, else None."""
    if user is None:
        # For HTMX requests, return HX-Redirect header
        if request.headers.get("HX-Request"):
            response = Response(status_code=401)
            response.headers["HX-Redirect"] = "/pipeline/login"
            return response
        return Response(status_code=401, content="Unauthorized")
    return None


def _apply_my_leads_filter(lead_query, user):
    """Apply 'My Leads' filter using assigned_to ID or name match."""
    # Try numeric ID match first
    if user.az_user_id:
        try:
            user_id_int = int(user.az_user_id)
            logger.info(f"My Leads filter: assigned_to={user_id_int} for user '{user.display_name}'")
            return lead_query.where(Lead.assigned_to == user_id_int)
        except (ValueError, TypeError):
            logger.warning(f"az_user_id '{user.az_user_id}' is not numeric, falling back to name match")

    # Fallback: match by first name from display_name
    if user.display_name:
        first_name = user.display_name.split()[0] if user.display_name.strip() else None
        if first_name:
            logger.info(f"My Leads filter: name match on firstname='{first_name}'")
            return lead_query.where(Lead.assign_to_firstname == first_name)

    logger.warning(f"My Leads filter: no user_id or name available, showing all leads")
    return lead_query


def _apply_filters(lead_query, user, view: str, producers: str = "", activity_days: str = ""):
    """Apply all filters to a lead query."""
    if view == "my":
        lead_query = _apply_my_leads_filter(lead_query, user)

    if producers:
        producer_list = [p.strip() for p in producers.split(",") if p.strip()]
        if producer_list:
            lead_query = lead_query.where(Lead.assign_to_firstname.in_(producer_list))

    if activity_days:
        if activity_days.endswith("+"):
            # "90+" means 90 days or older
            days = int(activity_days[:-1])
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
            lead_query = lead_query.where(Lead.last_activity_date <= cutoff)
        elif activity_days.isdigit():
            days = int(activity_days)
            cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
            lead_query = lead_query.where(Lead.last_activity_date >= cutoff)

    return lead_query


@router.get("/pipeline/api/producers")
async def get_producers(request: Request):
    """Return distinct producer names from leads."""
    user = await get_current_user(request)
    if user is None:
        return []

    async with async_session() as db:
        result = await db.execute(
            select(
                Lead.assign_to_firstname,
                Lead.assign_to_lastname,
            )
            .where(Lead.assign_to_firstname.isnot(None))
            .where(Lead.assign_to_firstname != "")
            .distinct()
            .order_by(Lead.assign_to_firstname)
        )
        rows = result.all()

    return [
        {"firstname": r[0], "lastname": r[1] or ""}
        for r in rows
    ]


@router.get("/pipeline/api/board/all", response_class=HTMLResponse)
async def get_all_boards(
    request: Request,
    view: str = "all",
    producers: str = "",
    activity_days: str = "",
):
    """Return kanban boards for ALL pipelines."""
    user = await get_current_user(request)
    auth_redirect = _require_auth(request, user)
    if auth_redirect:
        return auth_redirect

    async with async_session() as db:
        # Get all pipelines ordered alphabetically
        result = await db.execute(
            select(Pipeline).order_by(Pipeline.name)
        )
        pipelines = result.scalars().all()

        # Get all stages ordered by pipeline then seq
        result = await db.execute(
            select(Stage).order_by(Stage.pipeline_id, Stage.seq)
        )
        all_stages = result.scalars().all()

        # Build lead query
        lead_query = select(Lead)
        lead_query = _apply_filters(lead_query, user, view, producers, activity_days)
        lead_query = lead_query.order_by(Lead.last_activity_date.desc().nullslast())
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

    # Group stages by pipeline
    stages_by_pipeline = {}
    for stage in all_stages:
        pid = str(stage.pipeline_id)
        if pid not in stages_by_pipeline:
            stages_by_pipeline[pid] = []
        stages_by_pipeline[pid].append(stage)

    # Group leads by stage
    leads_by_stage = {}
    for lead in all_leads:
        stage_key = str(lead.stage_id)
        if stage_key not in leads_by_stage:
            leads_by_stage[stage_key] = []
        leads_by_stage[stage_key].append(lead)

    return templates.TemplateResponse(
        "partials/kanban_all.html",
        {
            "request": request,
            "pipelines": pipelines,
            "stages_by_pipeline": stages_by_pipeline,
            "leads_by_stage": leads_by_stage,
            "view": view,
        },
    )


@router.get("/pipeline/api/board/{pipeline_id}", response_class=HTMLResponse)
async def get_board(
    request: Request,
    pipeline_id: str,
    view: str = "all",
    producers: str = "",
    activity_days: str = "",
):
    """Return kanban board HTML partial for a single pipeline."""
    user = await get_current_user(request)
    auth_redirect = _require_auth(request, user)
    if auth_redirect:
        return auth_redirect

    async with async_session() as db:
        # Get stages for this pipeline, ordered by seq
        result = await db.execute(
            select(Stage)
            .where(Stage.pipeline_id == pipeline_id)
            .order_by(Stage.seq)
        )
        stages = result.scalars().all()

        # Get stage IDs for this pipeline
        stage_ids = [s.id for s in stages]

        # Query leads by stage_id (more reliable than pipeline_id)
        if stage_ids:
            lead_query = select(Lead).where(Lead.stage_id.in_(stage_ids))
        else:
            lead_query = select(Lead).where(Lead.pipeline_id == pipeline_id)

        lead_query = _apply_filters(lead_query, user, view, producers, activity_days)
        lead_query = lead_query.order_by(Lead.last_activity_date.desc().nullslast())
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

    # Group leads by stage
    leads_by_stage = {}
    for lead in all_leads:
        stage_key = str(lead.stage_id)
        if stage_key not in leads_by_stage:
            leads_by_stage[stage_key] = []
        leads_by_stage[stage_key].append(lead)

    return templates.TemplateResponse(
        "partials/kanban.html",
        {
            "request": request,
            "stages": stages,
            "leads_by_stage": leads_by_stage,
            "pipeline_id": pipeline_id,
            "view": view,
        },
    )


@router.get("/pipeline/api/sync-status", response_class=HTMLResponse)
async def sync_status(request: Request):
    """Return sync status badge HTML partial."""
    user = await get_current_user(request)
    if user is None:
        return HTMLResponse("")

    async with async_session() as db:
        result = await db.execute(
            select(func.max(Lead.synced_at))
        )
        last_sync = result.scalar_one_or_none()

    if last_sync:
        delta = datetime.utcnow() - last_sync
        minutes_ago = int(delta.total_seconds() / 60)
        if minutes_ago < 1:
            sync_text = "Just now"
        elif minutes_ago == 1:
            sync_text = "1 min ago"
        else:
            sync_text = f"{minutes_ago} min ago"
    else:
        sync_text = "Never"

    return templates.TemplateResponse(
        "partials/sync_status.html",
        {"request": request, "sync_text": sync_text},
    )
