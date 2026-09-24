"""
Map a Deputy employee to the RingCentral extension ID the DND endpoints need.

Lookup order:
1. Learned mapping in Redis (persistent volume, survives deploys)
2. shared/user_mappings.json -> ringcentral_member_id
3. Live lookup: Deputy employee email/name -> RingCentral extension list

A live lookup is saved to Redis, so it costs one lookup per person, and logs the
JSON entry to commit so user_mappings.json catches up. A 404 from RingCentral on a
stored ID triggers a fresh lookup (see resolve_target(refresh=True)).
Match by email first, then exact full name; anything ambiguous is logged, not guessed.
Extension numbers are not used to match: they get reassigned (101 went from Erin to Ilse).
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from shared import find_by_deputy_id

from .config import get_settings
from .redis_client import get_redis

logger = logging.getLogger(__name__)
settings = get_settings()

REDIS_KEY = "deputy:rc_target:{}"


@dataclass
class RingCentralTarget:
    extension_id: str
    name: str
    source: str  # "redis", "mapping", or "lookup"


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def match_extension(extensions: list[dict], emails: set[str], full_name: str) -> Optional[dict]:
    """Pick the one RingCentral user matching the email(s), else the exact full name. None if 0 or 2+."""
    users = [e for e in extensions if (e.get("type") or "User") == "User"]
    for candidates in (
        [e for e in users if emails and _norm(e.get("email") or "") in emails],
        [e for e in users if full_name and _norm(e.get("name") or "") == _norm(full_name)],
    ):
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.warning(f"Ambiguous RingCentral match for {full_name!r}: {[c.get('name') for c in candidates]}")
            return None
    return None


async def _deputy_get(client: httpx.AsyncClient, path: str) -> dict:
    response = await client.get(
        f"{settings.deputy_base_url.rstrip('/')}/api/v1/resource/{path}",
        headers={"Authorization": f"Bearer {settings.deputy_access_token}", "Accept": "application/json"},
    )
    response.raise_for_status()
    return response.json()


async def _lookup(deputy_id: str) -> Optional[RingCentralTarget]:
    if not settings.deputy_base_url or not settings.deputy_access_token:
        logger.warning(f"Deputy API not configured; cannot look up Deputy employee {deputy_id}")
        return None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            employee = await _deputy_get(client, f"Employee/{deputy_id}")
            emails: set[str] = set()
            if employee.get("Contact"):
                contact = await _deputy_get(client, f"Contact/{employee['Contact']}")
                values = [contact.get(k) for k in ("Email", "Email1", "Email2")]
                emails = {_norm(v) for v in values if isinstance(v, str) and "@" in v}
            full_name = f"{employee.get('FirstName') or ''} {employee.get('LastName') or ''}".strip() or employee.get("DisplayName", "")

            response = await client.get(f"{settings.ringcentral_service_url}/api/ringcentral/extensions")
            response.raise_for_status()
            extensions = response.json()
    except Exception as e:
        logger.error(f"Lookup failed for Deputy employee {deputy_id}: {e}")
        return None

    match = match_extension(extensions, emails, full_name)
    if not match:
        logger.warning(f"No unique RingCentral user for Deputy employee {deputy_id} ({full_name}); add them to shared/user_mappings.json")
        return None

    target = RingCentralTarget(extension_id=str(match["id"]), name=match.get("name") or full_name, source="lookup")
    await (await get_redis()).set(REDIS_KEY.format(deputy_id), json.dumps({"extension_id": target.extension_id, "name": target.name}))
    entry = {"name": target.name, "deputy_id": str(deputy_id), "ringcentral_member_id": target.extension_id,
             "ringcentral_extension_id": match.get("extension_number", "")}
    logger.warning(f"Resolved Deputy employee {deputy_id} via lookup and cached it; add to shared/user_mappings.json: {json.dumps(entry)}")
    return target


async def resolve_target(deputy_id: str, refresh: bool = False) -> Optional[RingCentralTarget]:
    """Return the RingCentral extension to update for a Deputy employee. refresh=True skips stored IDs."""
    if not refresh:
        cached = await (await get_redis()).get(REDIS_KEY.format(deputy_id))
        if cached:
            data = json.loads(cached)
            return RingCentralTarget(data["extension_id"], data["name"], "redis")
        user = find_by_deputy_id(deputy_id)
        if user and user.get("ringcentral_member_id"):
            return RingCentralTarget(user["ringcentral_member_id"], user.get("name", "Unknown"), "mapping")
    return await _lookup(deputy_id)
