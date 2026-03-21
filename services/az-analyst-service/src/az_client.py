"""AgencyZoom API client for the AZ analyst service.

Handles system auth for live data fetching (notes, tasks, lead detail).
"""

import asyncio
import logging
import time

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Rate limiting: 2 seconds between requests (max 30/min)
REQUEST_DELAY_SECONDS = 2.0
RATE_LIMIT_RETRY_SECONDS = 65
MAX_RETRIES = 3

# System token cache
_system_token_cache = {
    "access_token": None,
    "expires_at": 0,
}


async def _rate_limit_delay():
    """Proactive delay between AZ API calls to stay under rate limit."""
    await asyncio.sleep(REQUEST_DELAY_SECONDS)


async def _make_request(
    method: str,
    path: str,
    jwt: str,
    json: dict = None,
    params: dict = None,
) -> dict | list:
    """Make an authenticated request to the AgencyZoom API with rate limit handling."""
    url = f"{settings.agencyzoom_api_url}{path}"
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        async with httpx.AsyncClient() as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params, timeout=30.0)
            else:
                response = await client.post(url, headers=headers, json=json, timeout=30.0)

        if response.status_code == 429:
            logger.warning(f"Rate limited by AgencyZoom, waiting {RATE_LIMIT_RETRY_SECONDS}s (attempt {attempt + 1})")
            await asyncio.sleep(RATE_LIMIT_RETRY_SECONDS)
            continue

        if response.status_code == 401:
            logger.error("AgencyZoom returned 401 - token may be expired")
            raise Exception("AgencyZoom authentication expired")

        if response.status_code != 200:
            logger.error(f"AgencyZoom API error: {response.status_code} - {response.text[:500]}")
            raise Exception(f"AgencyZoom API error: {response.status_code}")

        return response.json()

    raise Exception("AgencyZoom API rate limit exceeded after retries")


async def system_login() -> str:
    """Get a system JWT using env var credentials. Caches for 23 hours."""
    current_time = time.time()

    if _system_token_cache["access_token"] and current_time < _system_token_cache["expires_at"]:
        return _system_token_cache["access_token"]

    logger.info("Authenticating with AgencyZoom (system credentials)")

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
        logger.error(f"System auth failed: {response.status_code} - {response.text}")
        raise Exception(f"AgencyZoom system auth failed: {response.status_code}")

    data = response.json()
    token = data.get("jwt") or data.get("accessToken")
    if not token:
        raise Exception("No JWT in system auth response")

    _system_token_cache["access_token"] = token
    _system_token_cache["expires_at"] = current_time + (23 * 60 * 60)

    logger.info("System authentication successful")
    return token


async def fetch_lead_notes(jwt: str, lead_id: int) -> list[dict]:
    """Fetch notes for a specific lead."""
    await _rate_limit_delay()
    data = await _make_request("GET", f"/v1/api/leads/{lead_id}/notes", jwt)
    if isinstance(data, list):
        return data
    return data.get("notes", data.get("items", []))


async def fetch_lead_tasks(jwt: str, lead_id: int) -> list[dict]:
    """Fetch tasks for a specific lead."""
    await _rate_limit_delay()
    data = await _make_request("GET", f"/v1/api/leads/{lead_id}/tasks", jwt)
    if isinstance(data, list):
        return data
    return data.get("tasks", data.get("items", []))


async def fetch_lead_detail(jwt: str, lead_id: int) -> dict:
    """Fetch full detail for a specific lead."""
    await _rate_limit_delay()
    return await _make_request("GET", f"/v1/api/leads/{lead_id}", jwt)


async def search_tasks(
    jwt: str,
    assignee_id: int = None,
    date_from: str = None,
    date_to: str = None,
) -> list[dict]:
    """Search tasks with optional filters."""
    await _rate_limit_delay()
    body = {}
    if assignee_id is not None:
        body["assignedTo"] = assignee_id
    if date_from:
        body["dateFrom"] = date_from
    if date_to:
        body["dateTo"] = date_to

    data = await _make_request("POST", "/v1/api/tasks/list", jwt, json=body)
    if isinstance(data, list):
        return data
    return data.get("tasks", data.get("items", []))
