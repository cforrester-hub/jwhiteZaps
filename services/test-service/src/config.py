"""
Application configuration using Pydantic settings.
Environment variables are automatically loaded and validated.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = "postgresql://zapier:zapier@localhost:5432/zapier_replacement"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Loki (logging)
    loki_url: str = "http://localhost:3100"

    # Application
    log_level: str = "INFO"
    service_name: str = "test-service"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Using lru_cache ensures settings are only loaded once.
    """
    return Settings()
