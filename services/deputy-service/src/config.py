"""Configuration settings for Deputy service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables."""

    # Deputy API Configuration
    deputy_base_url: str = ""  # e.g., https://yourcompany.na.deputy.com
    deputy_access_token: str = ""  # Permanent token or OAuth token

    # Redis Configuration (for dedupe locking)
    redis_url: str = "redis://redis:6379/0"

    # Dedupe Configuration
    dedupe_lock_ttl: int = 30  # Seconds to hold dedupe lock
    dedupe_completed_ttl: int = 3600  # Seconds to remember completed events

    # Service Configuration
    log_level: str = "INFO"

    class Config:
        env_prefix = ""
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
