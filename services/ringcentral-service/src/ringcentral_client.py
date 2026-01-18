"""
RingCentral API client for call logs, recordings, and AI insights.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RingCentralClient:
    """Client for interacting with RingCentral API."""

    def __init__(self):
        self.server_url = settings.ringcentral_server_url
        self.client_id = settings.ringcentral_client_id
        self.client_secret = settings.ringcentral_client_secret
        self.jwt_token = settings.ringcentral_jwt_token
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

    async def _ensure_authenticated(self):
        """Ensure we have a valid access token."""
        if self.access_token and self.token_expires_at:
            if datetime.now() < self.token_expires_at - timedelta(minutes=5):
                return

        await self._authenticate()

    async def _authenticate(self):
        """Authenticate using JWT and get access token."""
        logger.info("Authenticating with RingCentral API...")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.server_url}/restapi/oauth/token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": self.jwt_token,
                },
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                logger.error(f"Authentication failed: {response.status_code} - {response.text}")
                raise Exception(f"RingCentral authentication failed: {response.text}")

            data = response.json()
            self.access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in)
            logger.info("Successfully authenticated with RingCentral")

    async def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an authenticated request to the RingCentral API."""
        await self._ensure_authenticated()

        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{self.server_url}{endpoint}",
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                **kwargs,
            )

            if response.status_code == 401:
                # Token expired, re-authenticate and retry
                await self._authenticate()
                response = await client.request(
                    method,
                    f"{self.server_url}{endpoint}",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    **kwargs,
                )

            if response.status_code not in (200, 201, 204):
                logger.error(f"API request failed: {response.status_code} - {response.text}")
                raise Exception(f"RingCentral API error: {response.status_code} - {response.text}")

            if response.status_code == 204:
                return {}

            return response.json()

    async def test_connection(self) -> dict:
        """Test the connection to RingCentral API."""
        await self._ensure_authenticated()
        # Get account info to verify connection
        return await self._make_request("GET", "/restapi/v1.0/account/~")

    async def get_call_log(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        direction: Optional[str] = None,
        call_type: Optional[str] = None,
        per_page: int = 100,
        page: int = 1,
    ) -> dict:
        """
        Fetch call log records.

        Args:
            date_from: Start date for filtering calls
            date_to: End date for filtering calls
            direction: Filter by direction ('Inbound' or 'Outbound')
            call_type: Filter by type ('Voice', 'Fax', etc.)
            per_page: Number of records per page (max 250)
            page: Page number
        """
        params = {
            "view": "Detailed",
            "perPage": min(per_page, 250),
            "page": page,
        }

        if date_from:
            params["dateFrom"] = date_from.isoformat()
        if date_to:
            params["dateTo"] = date_to.isoformat()
        if direction:
            params["direction"] = direction
        if call_type:
            params["type"] = call_type

        return await self._make_request(
            "GET",
            "/restapi/v1.0/account/~/call-log",
            params=params,
        )

    async def get_call_recording(self, recording_id: str) -> dict:
        """
        Get recording metadata.

        Args:
            recording_id: The recording ID from call log
        """
        return await self._make_request(
            "GET",
            f"/restapi/v1.0/account/~/recording/{recording_id}",
        )

    async def get_recording_content_url(self, content_uri: str) -> str:
        """
        Get the URL to download recording content with access token.

        Args:
            content_uri: The contentUri from recording metadata
        """
        await self._ensure_authenticated()
        # Append access token for direct download
        if "?" in content_uri:
            return f"{content_uri}&access_token={self.access_token}"
        return f"{content_uri}?access_token={self.access_token}"

    async def get_ringsense_insights(self, recording_id: str) -> dict:
        """
        Get RingSense AI insights for a call recording.

        Args:
            recording_id: The recording ID from call log
        """
        try:
            return await self._make_request(
                "GET",
                f"/ai/ringsense/v1/public/accounts/~/domains/pbx/records/{recording_id}/insights",
            )
        except Exception as e:
            logger.warning(f"Could not fetch RingSense insights for {recording_id}: {e}")
            return {"error": str(e), "available": False}

    async def get_call_with_details(self, call_id: str) -> dict:
        """
        Get a single call record with full details.

        Args:
            call_id: The call ID
        """
        return await self._make_request(
            "GET",
            f"/restapi/v1.0/account/~/call-log/{call_id}",
            params={"view": "Detailed"},
        )


# Singleton instance
_client: Optional[RingCentralClient] = None


def get_ringcentral_client() -> RingCentralClient:
    """Get the RingCentral client singleton."""
    global _client
    if _client is None:
        _client = RingCentralClient()
    return _client
