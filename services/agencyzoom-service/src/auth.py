"""AgencyZoom authentication handling with JWT token management."""

import logging
import time
from datetime import datetime
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Token cache
_token_cache = {
    "access_token": None,
    "expires_at": 0,
}


async def get_access_token() -> str:
    """
    Get a valid access token, refreshing if necessary.

    Returns:
        str: Valid JWT access token

    Raises:
        Exception: If authentication fails
    """
    current_time = time.time()

    # Check if we have a valid cached token
    if _token_cache["access_token"] and current_time < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    # Need to authenticate
    logger.info("Authenticating with AgencyZoom API")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.agencyzoom_api_url}/v1/api/auth/login",
            json={
                "username": settings.agencyzoom_username,
                "password": settings.agencyzoom_password,
            },
            timeout=30.0,
        )

        if response.status_code != 200:
            logger.error(f"AgencyZoom auth failed: {response.status_code} - {response.text}")
            raise Exception(f"AgencyZoom authentication failed: {response.status_code}")

        data = response.json()
        # AgencyZoom returns 'jwt' not 'accessToken'
        access_token = data.get("jwt") or data.get("accessToken")

        if not access_token:
            logger.error(f"No token in response: {data}")
            raise Exception("No access token in auth response")

        # Cache the token (AgencyZoom tokens typically expire in 24 hours)
        # We'll set expiry to 23 hours to be safe
        _token_cache["access_token"] = access_token
        _token_cache["expires_at"] = current_time + (23 * 60 * 60)  # 23 hours

        logger.info("Successfully authenticated with AgencyZoom")
        return access_token


def clear_token_cache():
    """Clear the token cache (useful if token becomes invalid)."""
    _token_cache["access_token"] = None
    _token_cache["expires_at"] = 0
    logger.info("Token cache cleared")


async def get_auth_headers() -> dict:
    """Get headers with Bearer token for API requests."""
    token = await get_access_token()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
