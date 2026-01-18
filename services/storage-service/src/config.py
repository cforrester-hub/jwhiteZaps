"""Configuration settings for the storage service."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # DigitalOcean Spaces configuration
    # Create a Space at: https://cloud.digitalocean.com/spaces
    # Generate keys at: https://cloud.digitalocean.com/account/api/spaces
    spaces_access_key: str = ""
    spaces_secret_key: str = ""
    spaces_region: str = "nyc3"  # e.g., nyc3, sfo3, ams3, sgp1
    spaces_bucket: str = "call-recordings"  # Your Space name

    # Optional: Custom endpoint (if not using default DO Spaces)
    spaces_endpoint: str = ""  # Leave empty for default: {region}.digitaloceanspaces.com

    # Public URL base for accessing files
    # Default: https://{bucket}.{region}.digitaloceanspaces.com
    # Can also use CDN: https://{bucket}.{region}.cdn.digitaloceanspaces.com
    spaces_public_url: str = ""

    # Logging
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def endpoint_url(self) -> str:
        """Get the S3 endpoint URL."""
        if self.spaces_endpoint:
            return self.spaces_endpoint
        return f"https://{self.spaces_region}.digitaloceanspaces.com"

    @property
    def public_base_url(self) -> str:
        """Get the public URL base for files."""
        if self.spaces_public_url:
            return self.spaces_public_url.rstrip("/")
        return f"https://{self.spaces_bucket}.{self.spaces_region}.digitaloceanspaces.com"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
