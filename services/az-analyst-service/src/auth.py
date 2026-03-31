"""API key authentication for the AZ analyst service."""

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from .config import get_settings

settings = get_settings()

api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify the API key from the X-API-Key header."""
    if api_key != settings.analyst_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
