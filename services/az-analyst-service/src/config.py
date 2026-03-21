"""Configuration settings for the AZ analyst service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database (read-only access to pipeline-dashboard tables)
    database_url: str = "postgresql://zapier:password@postgres:5432/zapier_replacement"

    # AgencyZoom API
    agencyzoom_api_url: str = "https://api.agencyzoom.com"
    agencyzoom_username: str = ""
    agencyzoom_password: str = ""

    # API key for authenticating requests
    analyst_api_key: str = ""

    # Timezone
    az_timezone: str = "America/Los_Angeles"

    # Cap live AZ API calls per request
    max_live_api_calls: int = 15

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
