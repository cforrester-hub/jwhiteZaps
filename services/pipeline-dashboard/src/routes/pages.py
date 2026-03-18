"""Page routes: full HTML pages."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ..auth import get_current_user
from ..database import Pipeline, async_session

logger = logging.getLogger(__name__)
router = APIRouter()

templates = Jinja2Templates(directory="src/templates")


@router.get("/pipeline/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """Render login page."""
    error_message = None
    if error == "invalid_credentials":
        error_message = "Invalid username or password."
    elif error == "server_error":
        error_message = "An error occurred. Please try again."

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": error_message},
    )


@router.get("/pipeline/", response_class=HTMLResponse)
@router.get("/pipeline", response_class=HTMLResponse)
async def board_page(request: Request):
    """Render main board page. Redirects to login if not authenticated."""
    user = await get_current_user(request)
    if user is None:
        return RedirectResponse(url="/pipeline/login", status_code=302)

    # Fetch available pipelines, sorted alphabetically
    async with async_session() as db:
        result = await db.execute(
            select(Pipeline).order_by(Pipeline.name)
        )
        pipelines = result.scalars().all()

    return templates.TemplateResponse(
        "board.html",
        {
            "request": request,
            "user": user,
            "pipelines": pipelines,
        },
    )
