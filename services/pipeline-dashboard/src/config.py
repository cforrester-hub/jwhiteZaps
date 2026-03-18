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

    # Session
    session_expiry_hours: int = 8

    # Sync
    sync_interval_cron: str = "3,8,13,18,23,28,33,38,43,48,53,58 * * * *"

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
