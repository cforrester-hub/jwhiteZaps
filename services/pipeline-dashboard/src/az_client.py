"""AgencyZoom API client for pipeline dashboard.

Handles two auth contexts:
1. System auth — env var credentials for background sync
2. User auth — per-producer login for dashboard access
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Rate limiting: 2 seconds between requests (max 30/min)
REQUEST_DELAY_SECONDS = 2.0
RATE_LIMIT_RETRY_SECONDS = 65
MAX_RETRIES = 3

# System token cache (for background sync)
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
) -> dict:
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


# ---------------------------------------------------------------------------
# System Auth (for background sync)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# User Auth (for producer login)
# ---------------------------------------------------------------------------

async def user_login(username: str, password: str) -> dict:
    """
    Authenticate a producer with their own AZ credentials.

    Returns: {"jwt": str, "ownerAgent": bool}
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.agencyzoom_api_url}/v1/api/auth/login",
            json={"username": username, "password": password},
            timeout=30.0,
        )

    if response.status_code == 400:
        return None  # Invalid credentials

    if response.status_code != 200:
        logger.error(f"User auth failed: {response.status_code} - {response.text}")
        raise Exception(f"AgencyZoom auth error: {response.status_code}")

    return response.json()


# ---------------------------------------------------------------------------
# Data Fetching
# ---------------------------------------------------------------------------

async def fetch_producers(jwt: str) -> list[dict]:
    """
    Fetch list of producers from AgencyZoom.

    Returns: [{"id": "123", "name": "John Doe"}, ...]
    """
    data = await _make_request("GET", "/v1/api/text-thread/producer", jwt)
    return data.get("producers", [])


async def fetch_pipelines_and_stages(jwt: str) -> list[dict]:
    """
    Fetch all pipelines with their stages.

    Returns: [{"id": "1", "name": "...", "type": "...", "seq": 0, "status": 0,
               "stages": [{"id": "1", "name": "...", "seq": 0, "status": 0}]}]
    """
    return await _make_request("GET", "/v1/api/pipelines-and-stages", jwt)


async def fetch_leads_page(
    jwt: str,
    pipeline_id: Optional[int] = None,
    page: int = 0,
    page_size: int = 100,
    assigned_to: Optional[int] = None,
) -> dict:
    """
    Fetch a page of leads, optionally filtered by pipeline and assignee.

    Returns: {"totalCount": N, "page": N, "pageSize": N, "leads": [...]}
    """
    body = {
        "pageSize": page_size,
        "page": page,
        "sort": "lastEnterStageDate",
        "order": "desc",
    }
    if pipeline_id is not None:
        body["workflowId"] = pipeline_id
    if assigned_to is not None:
        body["assignedTo"] = assigned_to

    return await _make_request("POST", "/v1/api/leads/list", jwt, json=body)


async def fetch_all_leads_for_pipeline(jwt: str, pipeline_id: int) -> list[dict]:
    """Fetch all leads for a pipeline, handling pagination."""
    all_leads = []
    page = 0
    page_size = 100

    while True:
        data = await fetch_leads_page(jwt, pipeline_id=pipeline_id, page=page, page_size=page_size)
        leads = data.get("leads", [])
        all_leads.extend(leads)

        total_count = data.get("totalCount", 0)
        if (page + 1) * page_size >= total_count or not leads:
            break

        page += 1
        await _rate_limit_delay()

    return all_leads


async def fetch_pipeline_counts(jwt: str, assigned_to: Optional[int] = None) -> list[dict]:
    """
    Fetch lead counts per stage across all pipelines.

    Returns: [{"workflowStageId": "...", "count": N}, ...]
    """
    body = {}
    if assigned_to is not None:
        body["assignedTo"] = assigned_to

    data = await _make_request("POST", "/v1/api/leads/pipeline-count", jwt, json=body)
    return data.get("leadsCount", [])
