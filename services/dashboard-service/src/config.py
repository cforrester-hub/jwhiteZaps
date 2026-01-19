"""Configuration for the dashboard service."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Services to monitor (internal Docker network URLs)
    services: dict = {
        "ringcentral-service": "http://ringcentral-service:8000/api/ringcentral/health",
        "storage-service": "http://storage-service:8000/api/storage/health",
        "agencyzoom-service": "http://agencyzoom-service:8000/api/agencyzoom/health",
        "workflow-service": "http://workflow-service:8000/api/workflows/health",
        "test-service": "http://test-service:8000/api/test/health",
        "deputy-service": "http://deputy-service:8000/api/deputy/health",
    }

    # Employee status API key (for Windows desktop app authentication)
    # If not set, one will be generated on startup
    employee_status_api_key: Optional[str] = None

    # Internal API key for service-to-service communication
    # Deputy-service uses this to publish status updates
    internal_api_key: str = "internal-service-key"

    # Deputy service URL for checking current employee status on startup
    deputy_service_url: str = "http://deputy-service:8000"

    # RingCentral service URL for checking presence on startup
    ringcentral_service_url: str = "http://ringcentral-service:8000"

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
