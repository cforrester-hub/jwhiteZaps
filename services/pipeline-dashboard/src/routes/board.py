"""Board routes: kanban board HTMX partials."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import distinct, func, or_, select

from ..auth import get_current_user
from ..database import Employee, Lead, Pipeline, Stage, async_session
from .. import sync as sync_module

PACIFIC = ZoneInfo("America/Los_Angeles")

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


BUCKET_BOUNDS = {
    "today": (0, 0),
    "1": (1, 2),
    "3": (3, 6),
    "7": (7, 13),
    "14": (14, 29),
    "30": (30, 89),
    "90+": (90, None),
}


def _apply_filters(lead_query, user, view: str, producers: str = "", activity_buckets: str = "", search: str = ""):
    """Apply all filters to a lead query."""
    if view == "my":
        lead_query = _apply_my_leads_filter(lead_query, user)

    if producers:
        producer_list = [p.strip() for p in producers.split(",") if p.strip()]
        if producer_list:
            lead_query = lead_query.where(Lead.assign_to_firstname.in_(producer_list))

    if activity_buckets:
        bucket_keys = [b.strip() for b in activity_buckets.split(",") if b.strip()]
        if bucket_keys:
            now = datetime.now(PACIFIC)
            conditions = []
            includes_90_plus = "90+" in bucket_keys

            # Collect non-90+ buckets to compute contiguous range
            bounded_keys = [k for k in bucket_keys if k != "90+"]
            if bounded_keys:
                # Find overall min lower and max upper across selected buckets
                lowers = [BUCKET_BOUNDS[k][0] for k in bounded_keys]
                uppers = [BUCKET_BOUNDS[k][1] for k in bounded_keys]
                min_lower = min(lowers)
                max_upper = max(uppers)
                # Older boundary: inclusive (>=)
                upper_cutoff = (now - timedelta(days=max_upper)).strftime("%Y-%m-%d")
                # Newer boundary: +1 day with < to capture all datetimes on that day
                # (e.g. "2026-03-19T14:30:00" < "2026-03-20" works correctly)
                lower_cutoff = (now - timedelta(days=min_lower) + timedelta(days=1)).strftime("%Y-%m-%d")
                conditions.append(
                    (Lead.last_activity_date >= upper_cutoff) & (Lead.last_activity_date < lower_cutoff)
                )

            if includes_90_plus:
                cutoff_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
                conditions.append(
                    (Lead.last_activity_date < cutoff_90) | (Lead.last_activity_date.is_(None))
                )

            if conditions:
                lead_query = lead_query.where(or_(*conditions))

    if search and len(search) >= 2:
        tokens = [t.strip().lower() for t in search.split() if len(t.strip()) >= 2]
        if tokens:
            for token in tokens:
                pattern = f"{token}%"
                lead_query = lead_query.where(
                    or_(
                        func.lower(Lead.firstname).like(pattern),
                        func.lower(Lead.lastname).like(pattern),
                    )
                )

    return lead_query


def _compute_stats(leads, pipelines=None, stages=None):
    """Compute summary stats from a list of leads."""
    total = len(leads)

    # Per-pipeline lead counts
    pipeline_counts = []
    if pipelines and stages:
        # Build stage_id -> pipeline_id map
        stage_to_pipeline = {}
        for s in stages:
            stage_to_pipeline[str(s.id)] = str(s.pipeline_id)

        # Count leads per pipeline
        counts_by_pid = {}
        for lead in leads:
            pid = stage_to_pipeline.get(str(lead.stage_id), "")
            counts_by_pid[pid] = counts_by_pid.get(pid, 0) + 1

        # Build ordered list matching pipeline display order
        pipeline_name_map = {str(p.id): p.name for p in pipelines}
        for p in pipelines:
            pid = str(p.id)
            count = counts_by_pid.get(pid, 0)
            if count > 0:
                pipeline_counts.append({"id": pid, "name": p.name, "count": count})

    return {
        "total_leads": total,
        "pipeline_counts": pipeline_counts,
    }


@router.get("/pipeline/api/filter-counts")
async def get_filter_counts(
    request: Request,
    pipeline_id: str = "all",
    view: str = "all",
    producers: str = "",
    activity_buckets: str = "",
    search: str = "",
):
    """Return lead counts for filter items (producers and activity buckets)."""
    user = await get_current_user(request)
    if user is None:
        return JSONResponse({"producers": [], "activity": {}})

    async with async_session() as db:
        # Base query respecting pipeline + view filters (but NOT producer/activity)
        if pipeline_id == "all":
            base_query = select(Lead)
        else:
            result = await db.execute(
                select(Stage.id).where(Stage.pipeline_id == pipeline_id)
            )
            stage_ids = [r[0] for r in result.all()]
            if stage_ids:
                base_query = select(Lead).where(Lead.stage_id.in_(stage_ids))
            else:
                base_query = select(Lead).where(Lead.pipeline_id == pipeline_id)

        if view == "my":
            base_query = _apply_my_leads_filter(base_query, user)

        # Fetch all leads matching base filters
        result = await db.execute(base_query)
        all_leads = result.scalars().all()

    # Apply search filter to base results
    if search and len(search) >= 2:
        tokens = [t.strip().lower() for t in search.split() if len(t.strip()) >= 2]
        if tokens:
            def _matches_search(lead):
                fn = (lead.firstname or "").lower()
                ln = (lead.lastname or "").lower()
                return all(fn.startswith(t) or ln.startswith(t) for t in tokens)
            all_leads = [l for l in all_leads if _matches_search(l)]

    now = datetime.now(PACIFIC)
    today_str = now.strftime("%Y-%m-%d")

    # Producer counts (apply activity filter but not producer filter)
    filtered_for_producers = all_leads
    if activity_buckets:
        bucket_keys = [b.strip() for b in activity_buckets.split(",") if b.strip()]
        if bucket_keys:
            def _lead_in_buckets(lead, keys):
                for key in keys:
                    lower, upper = BUCKET_BOUNDS[key]
                    if key == "90+":
                        if not lead.last_activity_date:
                            return True
                        cutoff_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")
                        if lead.last_activity_date[:10] < cutoff_90:
                            return True
                    else:
                        if not lead.last_activity_date:
                            continue
                        date_str = lead.last_activity_date[:10]
                        upper_cutoff = (now - timedelta(days=upper)).strftime("%Y-%m-%d")
                        lower_cutoff = (now - timedelta(days=lower)).strftime("%Y-%m-%d")
                        if date_str >= upper_cutoff and date_str <= lower_cutoff:
                            return True
                return False

            filtered_for_producers = [l for l in all_leads if _lead_in_buckets(l, bucket_keys)]

    producer_counts = {}
    for lead in filtered_for_producers:
        if lead.assign_to_firstname:
            key = lead.assign_to_firstname
            if key not in producer_counts:
                producer_counts[key] = {"firstname": key, "lastname": lead.assign_to_lastname or "", "count": 0}
            producer_counts[key]["count"] += 1

    # Activity bucket counts (apply producer filter but not activity filter)
    # Each lead falls into exactly ONE bucket based on days since activity
    filtered_for_activity = all_leads
    if producers:
        producer_list = [p.strip() for p in producers.split(",") if p.strip()]
        if producer_list:
            filtered_for_activity = [l for l in all_leads if l.assign_to_firstname in producer_list]

    buckets = {"today": 0, "1": 0, "3": 0, "7": 0, "14": 0, "30": 0, "90+": 0}
    # Ordered bucket boundaries for exclusive assignment
    ordered_bounds = [("today", 0, 0), ("1", 1, 2), ("3", 3, 6), ("7", 7, 13), ("14", 14, 29), ("30", 30, 89)]

    for lead in filtered_for_activity:
        if not lead.last_activity_date:
            buckets["90+"] += 1
            continue
        date_str = lead.last_activity_date[:10]
        assigned = False
        for bucket_key, lower, upper in ordered_bounds:
            upper_cutoff = (now - timedelta(days=upper)).strftime("%Y-%m-%d")
            lower_cutoff = (now - timedelta(days=lower)).strftime("%Y-%m-%d")
            if date_str >= upper_cutoff and date_str <= lower_cutoff:
                buckets[bucket_key] += 1
                assigned = True
                break
        if not assigned:
            # Older than 90 days
            buckets["90+"] += 1

    return JSONResponse({
        "producers": sorted(producer_counts.values(), key=lambda p: p["firstname"]),
        "activity": buckets,
    })


@router.get("/pipeline/api/me")
async def get_current_user_producer(request: Request):
    """Return the current user's producer firstname by matching login email to employees."""
    user = await get_current_user(request)
    if user is None:
        return {"firstname": "", "lastname": "", "email": ""}

    async with async_session() as db:
        result = await db.execute(
            select(Employee).where(Employee.email == user.az_username)
        )
        employee = result.scalar_one_or_none()

    if employee:
        return {
            "firstname": employee.firstname or "",
            "lastname": employee.lastname or "",
            "email": employee.email or "",
        }

    return {"firstname": "", "lastname": "", "email": user.az_username}


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
    activity_buckets: str = "",
    search: str = "",
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
        lead_query = _apply_filters(lead_query, user, view, producers, activity_buckets, search)
        lead_query = lead_query.order_by(Lead.last_activity_date.desc().nullslast())
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

        # Terminal leads (Sold/Dead/Expired) — only when date filter active
        outcome_leads = {"sold": [], "dead": [], "expired": []}
        show_outcomes = False
        if activity_buckets:
            bucket_keys = [b.strip() for b in activity_buckets.split(",") if b.strip()]
            if bucket_keys and not (bucket_keys == ["90+"]):
                show_outcomes = True
                outcome_query = select(Lead).where(Lead.status.in_([2, 3, 5]))
                outcome_query = _apply_filters(outcome_query, user, view, producers, activity_buckets, search)
                outcome_query = outcome_query.order_by(Lead.last_activity_date.desc().nullslast())
                result = await db.execute(outcome_query)
                for lead in result.scalars().all():
                    if lead.status == 2:
                        outcome_leads["sold"].append(lead)
                    elif lead.status == 3:
                        outcome_leads["dead"].append(lead)
                    elif lead.status == 5:
                        outcome_leads["expired"].append(lead)

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

    stats = _compute_stats(all_leads, pipelines=pipelines, stages=all_stages)

    return templates.TemplateResponse(
        "partials/kanban_all.html",
        {
            "request": request,
            "pipelines": pipelines,
            "stages_by_pipeline": stages_by_pipeline,
            "leads_by_stage": leads_by_stage,
            "view": view,
            "outcome_leads": outcome_leads,
            "show_outcomes": show_outcomes,
            "outcome_sold": len(outcome_leads.get("sold", [])),
            "outcome_dead": len(outcome_leads.get("dead", [])),
            "outcome_expired": len(outcome_leads.get("expired", [])),
            **stats,
        },
    )


@router.get("/pipeline/api/board/{pipeline_id}", response_class=HTMLResponse)
async def get_board(
    request: Request,
    pipeline_id: str,
    view: str = "all",
    producers: str = "",
    activity_buckets: str = "",
    search: str = "",
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

        lead_query = _apply_filters(lead_query, user, view, producers, activity_buckets, search)
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

    stats = _compute_stats(all_leads)

    return templates.TemplateResponse(
        "partials/kanban.html",
        {
            "request": request,
            "stages": stages,
            "leads_by_stage": leads_by_stage,
            "pipeline_id": pipeline_id,
            "view": view,
            **stats,
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

    # If sync has been "in progress" for more than 90 minutes, treat as stale
    syncing = sync_module.sync_in_progress
    if syncing and sync_module.sync_started_at is not None:
        import time
        if time.monotonic() - sync_module.sync_started_at > 5400:
            syncing = False

    return templates.TemplateResponse(
        "partials/sync_status.html",
        {"request": request, "sync_text": sync_text, "syncing": syncing},
    )


# --- JSON API Endpoints for Data Analysis ---

STATUS_LABELS = {0: "new", 1: "quoted", 2: "won", 3: "lost", 4: "contacted", 5: "expired"}


def _serialize_lead(lead):
    """Convert a Lead ORM object to a JSON-serializable dict."""
    return {
        "id": lead.id,
        "firstname": lead.firstname,
        "lastname": lead.lastname,
        "phone": lead.phone,
        "email": lead.email,
        "status": lead.status,
        "lead_type": lead.lead_type,
        "pipeline_name": lead.workflow_name,
        "stage_name": lead.workflow_stage_name,
        "assigned_to_name": " ".join(filter(None, [lead.assign_to_firstname, lead.assign_to_lastname])) or None,
        "last_activity_date": lead.last_activity_date[:10] if lead.last_activity_date else None,
        "enter_stage_date": lead.enter_stage_date[:10] if lead.enter_stage_date else None,
        "contact_date": lead.contact_date[:10] if lead.contact_date else None,
        "premium": lead.premium,
        "quoted": lead.quoted,
        "lead_source": lead.lead_source_name,
    }


async def _build_filtered_query(db, user, pipeline_id=None, view="all", producers="",
                                  activity_buckets="", search="", status=""):
    """Build a filtered Lead query, returning (query, stage_ids_used)."""
    if pipeline_id:
        result = await db.execute(
            select(Stage.id).where(Stage.pipeline_id == pipeline_id)
        )
        stage_ids = [r[0] for r in result.all()]
        if stage_ids:
            lead_query = select(Lead).where(Lead.stage_id.in_(stage_ids))
        else:
            lead_query = select(Lead).where(Lead.pipeline_id == pipeline_id)
    else:
        lead_query = select(Lead)

    lead_query = _apply_filters(lead_query, user, view, producers, activity_buckets, search)

    if status:
        status_ints = [int(s.strip()) for s in status.split(",") if s.strip().isdigit()]
        if status_ints:
            lead_query = lead_query.where(Lead.status.in_(status_ints))

    return lead_query


@router.get("/pipeline/api/leads")
async def get_leads_json(
    request: Request,
    pipeline_id: str = "",
    view: str = "all",
    producers: str = "",
    activity_buckets: str = "",
    search: str = "",
    status: str = "",
    page: int = 0,
    page_size: int = 100,
):
    """Return paginated JSON lead data with filtering."""
    user = await get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    page_size = min(max(page_size, 1), 500)
    page = max(page, 0)

    async with async_session() as db:
        lead_query = await _build_filtered_query(
            db, user, pipeline_id or None, view, producers, activity_buckets, search, status
        )

        # Get total count
        count_query = select(func.count()).select_from(lead_query.subquery())
        total = (await db.execute(count_query)).scalar()

        # Fetch page
        lead_query = lead_query.order_by(Lead.last_activity_date.desc().nullslast())
        lead_query = lead_query.offset(page * page_size).limit(page_size)
        result = await db.execute(lead_query)
        leads = result.scalars().all()

    return JSONResponse({
        "total": total,
        "page": page,
        "page_size": page_size,
        "leads": [_serialize_lead(l) for l in leads],
    })


@router.get("/pipeline/api/stats/activity")
async def get_stats_activity(
    request: Request,
    pipeline_id: str = "",
    view: str = "all",
    producers: str = "",
    activity_buckets: str = "",
    search: str = "",
    status: str = "",
):
    """Return lead counts grouped by activity date and bucket."""
    user = await get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    now = datetime.now(PACIFIC)

    async with async_session() as db:
        lead_query = await _build_filtered_query(
            db, user, pipeline_id or None, view, producers, activity_buckets, search, status
        )

        # Fetch all leads and compute everything in Python
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

    total = len(all_leads)
    cutoff_90 = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    # by_date: count per date, last 90 days only
    date_counts = {}
    for lead in all_leads:
        if not lead.last_activity_date:
            continue
        dt = lead.last_activity_date[:10]
        if dt >= cutoff_90:
            date_counts[dt] = date_counts.get(dt, 0) + 1
    by_date = [{"date": d, "count": c} for d, c in sorted(date_counts.items(), reverse=True)]

    # Compute buckets
    ordered_bounds = [("today", 0, 0), ("1", 1, 2), ("3", 3, 6), ("7", 7, 13), ("14", 14, 29), ("30", 30, 89)]
    buckets = {"today": 0, "1": 0, "3": 0, "7": 0, "14": 0, "30": 0, "90+": 0}
    for lead in all_leads:
        if not lead.last_activity_date:
            buckets["90+"] += 1
            continue
        date_str = lead.last_activity_date[:10]
        assigned = False
        for bucket_key, lower, upper in ordered_bounds:
            upper_cutoff = (now - timedelta(days=upper)).strftime("%Y-%m-%d")
            lower_cutoff = (now - timedelta(days=lower)).strftime("%Y-%m-%d")
            if upper_cutoff <= date_str <= lower_cutoff:
                buckets[bucket_key] += 1
                assigned = True
                break
        if not assigned:
            buckets["90+"] += 1

    return JSONResponse({
        "total": total,
        "by_date": by_date,
        "by_bucket": buckets,
    })


@router.get("/pipeline/api/stats/producers")
async def get_stats_producers(
    request: Request,
    pipeline_id: str = "",
    view: str = "all",
    activity_buckets: str = "",
    search: str = "",
    status: str = "",
):
    """Return per-producer lead breakdown."""
    user = await get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    now = datetime.now(PACIFIC)

    async with async_session() as db:
        lead_query = await _build_filtered_query(
            db, user, pipeline_id or None, view, "", activity_buckets, search, status
        )
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

    # Group by producer
    producers_map = {}
    ordered_bounds = [("today", 0, 0), ("1", 1, 2), ("3", 3, 6), ("7", 7, 13), ("14", 14, 29), ("30", 30, 89)]

    for lead in all_leads:
        key = lead.assign_to_firstname or "(unassigned)"
        if key not in producers_map:
            producers_map[key] = {
                "firstname": lead.assign_to_firstname or "",
                "lastname": lead.assign_to_lastname or "",
                "total": 0,
                "by_status": {v: 0 for v in STATUS_LABELS.values()},
                "by_bucket": {"today": 0, "1": 0, "3": 0, "7": 0, "14": 0, "30": 0, "90+": 0},
            }
        p = producers_map[key]
        p["total"] += 1

        # Status
        status_label = STATUS_LABELS.get(lead.status, "new")
        p["by_status"][status_label] += 1

        # Bucket
        if not lead.last_activity_date:
            p["by_bucket"]["90+"] += 1
        else:
            date_str = lead.last_activity_date[:10]
            assigned = False
            for bucket_key, lower, upper in ordered_bounds:
                upper_cutoff = (now - timedelta(days=upper)).strftime("%Y-%m-%d")
                lower_cutoff = (now - timedelta(days=lower)).strftime("%Y-%m-%d")
                if upper_cutoff <= date_str <= lower_cutoff:
                    p["by_bucket"][bucket_key] += 1
                    assigned = True
                    break
            if not assigned:
                p["by_bucket"]["90+"] += 1

    result_list = sorted(producers_map.values(), key=lambda p: p["firstname"])
    return JSONResponse({"producers": result_list})


@router.get("/pipeline/api/stats/pipelines")
async def get_stats_pipelines(
    request: Request,
    view: str = "all",
    producers: str = "",
    activity_buckets: str = "",
    search: str = "",
):
    """Return per-pipeline lead counts with stage and status breakdowns."""
    user = await get_current_user(request)
    if user is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    async with async_session() as db:
        # Get all pipelines and stages
        result = await db.execute(select(Pipeline).order_by(Pipeline.name))
        pipelines = result.scalars().all()

        result = await db.execute(select(Stage).order_by(Stage.pipeline_id, Stage.seq))
        all_stages = result.scalars().all()

        # Get filtered leads
        lead_query = await _build_filtered_query(
            db, user, None, view, producers, activity_buckets, search
        )
        result = await db.execute(lead_query)
        all_leads = result.scalars().all()

    # Build stage_id -> pipeline_id and stage_id -> stage_name maps
    stage_to_pipeline = {}
    stage_name_map = {}
    stages_by_pipeline = {}
    for s in all_stages:
        pid = str(s.pipeline_id)
        sid = str(s.id)
        stage_to_pipeline[sid] = pid
        stage_name_map[sid] = s.name
        if pid not in stages_by_pipeline:
            stages_by_pipeline[pid] = []
        stages_by_pipeline[pid].append(s)

    pipeline_name_map = {str(p.id): p.name for p in pipelines}

    # Accumulate per-pipeline stats
    pipeline_data = {}
    for lead in all_leads:
        sid = str(lead.stage_id) if lead.stage_id else ""
        pid = stage_to_pipeline.get(sid, str(lead.pipeline_id) if lead.pipeline_id else "")
        if not pid:
            continue

        if pid not in pipeline_data:
            pipeline_data[pid] = {
                "id": pid,
                "name": pipeline_name_map.get(pid, "Unknown"),
                "total": 0,
                "stage_counts": {},
                "by_status": {v: 0 for v in STATUS_LABELS.values()},
            }
        pd = pipeline_data[pid]
        pd["total"] += 1

        # Stage count
        if sid:
            pd["stage_counts"][sid] = pd["stage_counts"].get(sid, 0) + 1

        # Status
        status_label = STATUS_LABELS.get(lead.status, "new")
        pd["by_status"][status_label] += 1

    # Build final response with ordered stages
    result_list = []
    for p in pipelines:
        pid = str(p.id)
        if pid not in pipeline_data:
            continue
        pd = pipeline_data[pid]
        by_stage = []
        for s in stages_by_pipeline.get(pid, []):
            sid = str(s.id)
            count = pd["stage_counts"].get(sid, 0)
            if count > 0:
                by_stage.append({"id": sid, "name": s.name, "count": count})
        result_list.append({
            "id": pd["id"],
            "name": pd["name"],
            "total": pd["total"],
            "by_stage": by_stage,
            "by_status": pd["by_status"],
        })

    return JSONResponse({"pipelines": result_list})
