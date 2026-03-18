"""Session authentication for the pipeline dashboard."""

import base64
import json
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, delete

from .az_client import fetch_producers, user_login
from .config import get_settings
from .database import Session, async_session

logger = logging.getLogger(__name__)
settings = get_settings()

COOKIE_NAME = "pd_session"


async def login_user(username: str, password: str) -> dict | None:
    """
    Authenticate user with AgencyZoom and create a session.

    Returns session dict on success, None on invalid credentials.
    """
    # Authenticate with AZ
    auth_result = await user_login(username, password)
    if auth_result is None:
        return None

    jwt = auth_result.get("jwt")
    if not jwt:
        return None

    is_owner = auth_result.get("ownerAgent", False)

    # Try to identify the user from the JWT payload or producer list
    display_name = username  # fallback to email
    az_user_id = None

    # Attempt to decode JWT payload (it's base64-encoded, not encrypted)
    try:
        payload_part = jwt.split(".")[1]
        # Add padding if needed
        padding = 4 - len(payload_part) % 4
        if padding != 4:
            payload_part += "=" * padding
        jwt_payload = json.loads(base64.urlsafe_b64decode(payload_part))
        # Common JWT fields for user identity
        az_user_id = str(jwt_payload.get("userId") or jwt_payload.get("sub") or jwt_payload.get("id") or "")
        jwt_name = jwt_payload.get("name") or jwt_payload.get("displayName") or ""
        if jwt_name:
            display_name = jwt_name
        logger.info(f"JWT decoded: user_id={az_user_id}, name={display_name}")
    except Exception as e:
        logger.warning(f"Could not decode JWT payload: {e}")

    # If JWT didn't give us a user ID, try the producer list
    if not az_user_id:
        try:
            producers = await fetch_producers(jwt)
            if producers and len(producers) == 1:
                # Single producer — must be this user
                az_user_id = str(producers[0].get("id", ""))
                display_name = producers[0].get("name", username)
            elif producers:
                # Multiple producers — store None, user gets "All Leads" by default
                logger.info(f"Multiple producers found ({len(producers)}), cannot auto-match user")
        except Exception as e:
            logger.warning(f"Could not fetch producers: {e}")

    # Create session
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=settings.session_expiry_hours)

    async with async_session() as db:
        async with db.begin():
            db.add(Session(
                id=session_id,
                az_user_id=az_user_id,
                az_username=username,
                az_jwt=jwt,
                display_name=display_name,
                is_owner_agent=1 if is_owner else 0,
                created_at=datetime.utcnow(),
                last_accessed=datetime.utcnow(),
                expires_at=expires_at,
            ))

    return {
        "session_id": session_id,
        "display_name": display_name,
        "az_user_id": az_user_id,
        "is_owner_agent": is_owner,
    }


async def get_current_user(request: Request) -> Session | None:
    """
    FastAPI dependency: get current authenticated user from session cookie.

    Returns the Session object or None if not authenticated.
    """
    session_id = request.cookies.get(COOKIE_NAME)
    if not session_id:
        return None

    async with async_session() as db:
        result = await db.execute(
            select(Session).where(
                Session.id == session_id,
                Session.expires_at > datetime.utcnow(),
            )
        )
        session = result.scalar_one_or_none()

        if session:
            # Update last_accessed
            session.last_accessed = datetime.utcnow()
            await db.commit()

        return session


async def logout_user(session_id: str):
    """Delete a session from the database."""
    async with async_session() as db:
        async with db.begin():
            await db.execute(
                delete(Session).where(Session.id == session_id)
            )


async def cleanup_expired_sessions():
    """Remove expired sessions from the database."""
    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                delete(Session).where(Session.expires_at < datetime.utcnow())
            )
            if result.rowcount > 0:
                logger.info(f"Cleaned up {result.rowcount} expired sessions")


def set_session_cookie(response: Response, session_id: str):
    """Set the session cookie on a response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        path="/pipeline",
        httponly=True,
        samesite="lax",
        max_age=settings.session_expiry_hours * 3600,
    )


def clear_session_cookie(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/pipeline")
