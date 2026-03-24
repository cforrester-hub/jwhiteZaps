"""Configuration settings for the pipeline dashboard service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://zapier:password@postgres:5432/zapier_replacement"

    # AgencyZoom API (system credentials for background sync)
    agencyzoom_api_url: str = "https://api.agencyzoom.com"
    agencyzoom_username: str = ""
    agencyzoom_password: str = ""

    # AZ Analyst API (for activity summary page)
    analyst_api_url: str = "http://az-analyst-service:8000"
    analyst_api_key: str = ""

    # Session
    session_expiry_hours: int = 8

    # Sync
    sync_interval_cron: str = "3,33 * * * *"

    # Timezone that AgencyZoom returns dates in (agency-level setting in AZ)
    az_timezone: str = "America/Los_Angeles"

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
