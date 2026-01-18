"""HTTP client for calling internal microservices."""

import logging
from typing import Any, Optional

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Shared HTTP client with connection pooling
_client: Optional[httpx.AsyncClient] = None


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared HTTP client."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_client():
    """Close the HTTP client (call on shutdown)."""
    global _client
    if _client:
        await _client.aclose()
        _client = None


class ServiceClient:
    """Base client for calling internal services."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        """Make a GET request to the service."""
        client = await get_client()
        url = f"{self.base_url}{path}"
        logger.debug(f"GET {url}")
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, json: Optional[dict] = None) -> dict:
        """Make a POST request to the service."""
        client = await get_client()
        url = f"{self.base_url}{path}"
        logger.debug(f"POST {url}")
        response = await client.post(url, json=json)
        response.raise_for_status()
        return response.json()

    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        try:
            await self.get("/health")
            return True
        except Exception:
            return False


class RingCentralClient(ServiceClient):
    """Client for the RingCentral service."""

    def __init__(self):
        super().__init__(settings.ringcentral_service_url)

    async def get_calls(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        direction: Optional[str] = None,
        per_page: int = 100,
        page: int = 1,
    ) -> dict:
        """Fetch call logs from RingCentral service."""
        params = {"per_page": per_page, "page": page}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        if direction:
            params["direction"] = direction
        return await self.get("/api/ringcentral/calls", params=params)

    async def get_call_details(
        self, call_id: str, include_recording: bool = True, include_ai_insights: bool = True
    ) -> dict:
        """Get details for a specific call."""
        params = {
            "include_recording": include_recording,
            "include_ai_insights": include_ai_insights,
        }
        return await self.get(f"/api/ringcentral/calls/{call_id}", params=params)

    async def get_recording(self, recording_id: str) -> dict:
        """Get recording metadata and download URL."""
        return await self.get(f"/api/ringcentral/recordings/{recording_id}")

    async def health_check(self) -> bool:
        """Check if RingCentral service is healthy."""
        try:
            await self.get("/api/ringcentral/health")
            return True
        except Exception:
            return False


class AgencyZoomClient(ServiceClient):
    """Client for the AgencyZoom service."""

    def __init__(self):
        super().__init__(settings.agencyzoom_service_url)

    async def search_by_phone(self, phone: str) -> dict:
        """Search for customers and leads by phone number."""
        return await self.post("/api/agencyzoom/search/phone", json={"phone": phone})

    async def create_customer_note(self, customer_id: str, content: str, note_type: str = "General") -> dict:
        """Create a note for a customer."""
        return await self.post(
            f"/api/agencyzoom/customers/{customer_id}/notes",
            json={"content": content, "note_type": note_type},
        )

    async def create_lead_note(self, lead_id: str, content: str, note_type: str = "General") -> dict:
        """Create a note for a lead."""
        return await self.post(
            f"/api/agencyzoom/leads/{lead_id}/notes",
            json={"content": content, "note_type": note_type},
        )

    async def health_check(self) -> bool:
        """Check if AgencyZoom service is healthy."""
        try:
            await self.get("/api/agencyzoom/health")
            return True
        except Exception:
            return False


class StorageClient(ServiceClient):
    """Client for the Storage service (DigitalOcean Spaces)."""

    def __init__(self):
        super().__init__(settings.storage_service_url)

    async def upload_from_url(
        self,
        url: str,
        filename: str,
        folder: str = "",
        content_type: str = "application/octet-stream",
        public: bool = True,
    ) -> dict:
        """Upload a file from a URL to storage."""
        return await self.post(
            "/api/storage/upload-from-url",
            json={
                "url": url,
                "filename": filename,
                "folder": folder,
                "content_type": content_type,
                "public": public,
            },
        )

    async def list_files(self, prefix: str = "", max_keys: int = 100) -> list:
        """List files in storage."""
        return await self.get("/api/storage/files", params={"prefix": prefix, "max_keys": max_keys})

    async def health_check(self) -> bool:
        """Check if Storage service is healthy."""
        try:
            await self.get("/api/storage/health")
            return True
        except Exception:
            return False


class TeamsClient(ServiceClient):
    """Client for the Microsoft Teams service (placeholder)."""

    def __init__(self):
        super().__init__(settings.teams_service_url)

    # Add Teams-specific methods as needed


class OneDriveClient(ServiceClient):
    """Client for the OneDrive service (placeholder)."""

    def __init__(self):
        super().__init__(settings.onedrive_service_url)

    # Add OneDrive-specific methods as needed


# Singleton instances
ringcentral = RingCentralClient()
agencyzoom = AgencyZoomClient()
storage = StorageClient()
teams = TeamsClient()
onedrive = OneDriveClient()
