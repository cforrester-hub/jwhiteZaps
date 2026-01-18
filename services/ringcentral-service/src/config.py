"""
Configuration settings for RingCentral service.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # RingCentral API settings
    ringcentral_client_id: str
    ringcentral_client_secret: str
    ringcentral_jwt_token: str
    ringcentral_server_url: str = "https://platform.ringcentral.com"

    # Service settings
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
