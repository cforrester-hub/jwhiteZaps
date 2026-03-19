"""Board routes: kanban board HTMX partials."""

import logging
from datetime import datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

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


@router.get("/pipeline/api/board/all", response_class=HTMLResponse)
async def get_all_boards(request: Request, view: str = "all"):
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
        if view == "my" and user.az_user_id:
            lead_query = lead_query.where(
                Lead.assigned_to == int(user.az_user_id)
            )
        lead_query = lead_query.order_by(Lead.enter_stage_date.desc())
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
async def get_board(request: Request, pipeline_id: str, view: str = "all"):
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

        if view == "my" and user.az_user_id:
            lead_query = lead_query.where(
                Lead.assigned_to == int(user.az_user_id)
            )

        lead_query = lead_query.order_by(Lead.enter_stage_date.desc())
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
