"""Configuration settings for the workflow service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database for tracking processed items
    database_url: str = "postgresql://zapier:password@postgres:5432/zapier_replacement"

    # Internal service URLs (Docker network)
    ringcentral_service_url: str = "http://ringcentral-service:8000"
    agencyzoom_service_url: str = "http://agencyzoom-service:8000"
    teams_service_url: str = "http://teams-service:8000"
    onedrive_service_url: str = "http://onedrive-service:8000"

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
