"""API key authentication for the AZ analyst service."""

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from .config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key_h: str | None = Security(api_key_header),
    api_key_q: str | None = Query(default=None, alias="api_key"),
):
    """Verify the API key from the X-API-Key header or api_key query param."""
    api_key = api_key_h or api_key_q
    if not api_key or api_key != settings.analyst_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
