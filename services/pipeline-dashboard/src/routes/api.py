"""API routes: login, logout, health, manual sync."""

import logging
import time

from fastapi import APIRouter, BackgroundTasks, Form, Request, Response
from fastapi.responses import RedirectResponse

from ..auth import (
    COOKIE_NAME,
    clear_session_cookie,
    get_current_user,
    login_user,
    logout_user,
    set_session_cookie,
)
from .. import sync as sync_module
from ..sync import sync_all

logger = logging.getLogger(__name__)
router = APIRouter()

# Rate limit: track last manual sync time per user (session_id -> timestamp)
_last_manual_sync: dict[str, float] = {}
SYNC_COOLDOWN_SECONDS = 300  # 5 minutes


@router.get("/pipeline/api/health")
async def health():
    return {"status": "healthy", "service": "pipeline-dashboard"}


@router.post("/pipeline/api/login")
async def api_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Authenticate with AgencyZoom credentials."""
    try:
        result = await login_user(username, password)
    except Exception as e:
        logger.error(f"Login error: {e}")
        return RedirectResponse(
            url="/pipeline/login?error=server_error",
            status_code=303,
        )

    if result is None:
        return RedirectResponse(
            url="/pipeline/login?error=invalid_credentials",
            status_code=303,
        )

    response = RedirectResponse(url="/pipeline/", status_code=303)
    set_session_cookie(response, result["session_id"])
    return response


@router.post("/pipeline/api/sync")
async def trigger_sync(request: Request, background_tasks: BackgroundTasks):
    """Manually trigger a data sync. Rate limited to once per 5 minutes per user."""
    user = await get_current_user(request)
    if user is None:
        return {"status": "error", "message": "Not authenticated"}

    session_id = request.cookies.get(COOKIE_NAME, "")
    now = time.time()
    last = _last_manual_sync.get(session_id, 0)
    remaining = int(SYNC_COOLDOWN_SECONDS - (now - last))

    if remaining > 0:
        minutes = remaining // 60
        seconds = remaining % 60
        return {
            "status": "rate_limited",
            "message": f"Please wait {minutes}m {seconds}s before syncing again",
            "retry_after": remaining,
        }

    _last_manual_sync[session_id] = now
    background_tasks.add_task(sync_all)
    logger.info(f"Manual sync triggered by {user.display_name}")
    return {"status": "started", "message": "Sync started in background"}


@router.post("/pipeline/api/logout")
async def api_logout(request: Request):
    """Destroy session and redirect to login."""
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await logout_user(session_id)

    response = RedirectResponse(url="/pipeline/login", status_code=303)
    clear_session_cookie(response)
    return response
