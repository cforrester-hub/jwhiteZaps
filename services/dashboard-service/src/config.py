"""Configuration for the dashboard service."""

from functools import lru_cache

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
    }

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
