"""Configuration for the transcription service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI Configuration
    openai_api_key: str = ""

    # Model Configuration
    whisper_model: str = "whisper-1"  # or "gpt-4o-mini-transcribe" for cheaper
    summary_model: str = "gpt-4o-mini"  # Fast and cheap for summaries

    # Service Configuration
    log_level: str = "INFO"
    max_audio_duration_seconds: int = 3600  # 1 hour max

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
