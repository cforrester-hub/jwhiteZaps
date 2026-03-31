"""API key authentication for the AZ analyst service."""

from fastapi import HTTPException, Query, Security
from fastapi.security import APIKeyHeader

from .config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key_header_val: str = Security(api_key_header),
    api_key: str = Query(default=None, include_in_schema=False),
):
    """Verify the API key from X-API-Key header or api_key query param."""
    key = api_key_header_val or api_key
    if key != settings.analyst_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
