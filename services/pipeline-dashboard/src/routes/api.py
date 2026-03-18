"""API routes: login, logout, health."""

import logging

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse

from ..auth import (
    COOKIE_NAME,
    clear_session_cookie,
    get_current_user,
    login_user,
    logout_user,
    set_session_cookie,
)

logger = logging.getLogger(__name__)
router = APIRouter()


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


@router.post("/pipeline/api/logout")
async def api_logout(request: Request):
    """Destroy session and redirect to login."""
    session_id = request.cookies.get(COOKIE_NAME)
    if session_id:
        await logout_user(session_id)

    response = RedirectResponse(url="/pipeline/login", status_code=303)
    clear_session_cookie(response)
    return response
