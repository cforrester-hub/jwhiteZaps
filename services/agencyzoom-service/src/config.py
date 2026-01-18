"""Configuration settings for the AgencyZoom service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # AgencyZoom API configuration
    # API Base URL
    agencyzoom_api_url: str = "https://api.agencyzoom.com"

    # Authentication credentials
    agencyzoom_username: str = ""
    agencyzoom_password: str = ""

    # Token caching (how long before expiry to refresh, in seconds)
    token_refresh_buffer: int = 300  # Refresh 5 minutes before expiry

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
