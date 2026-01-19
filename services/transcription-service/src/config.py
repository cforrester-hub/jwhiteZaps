"""Configuration for the transcription service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI Configuration
    openai_api_key: str = ""

    # Model Configuration
    # gpt-4o-transcribe is more accurate than whisper-1, especially for:
    # - Spelled-out names and letters
    # - Accents and varying speech patterns
    # - Noisy audio
    # Same price as whisper-1: $0.006/minute
    whisper_model: str = "gpt-4o-transcribe"
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
