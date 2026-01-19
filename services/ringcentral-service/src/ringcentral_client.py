"""
RingCentral API client for call logs, recordings, voicemails, and AI insights.
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

    async def get_voicemail_messages(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        per_page: int = 100,
        page: int = 1,
    ) -> dict:
        """
        Fetch voicemail messages from the message store.

        This is different from call logs - voicemail audio is accessed
        through the message-store API, not the call-log recording API.

        Args:
            date_from: Start date for filtering messages
            date_to: End date for filtering messages
            per_page: Number of records per page (max 250)
            page: Page number
        """
        params = {
            "messageType": "VoiceMail",
            "perPage": min(per_page, 250),
            "page": page,
        }

        if date_from:
            params["dateFrom"] = date_from.isoformat()
        if date_to:
            params["dateTo"] = date_to.isoformat()

        return await self._make_request(
            "GET",
            "/restapi/v1.0/account/~/extension/~/message-store",
            params=params,
        )

    async def get_voicemail_message(self, message_id: str) -> dict:
        """
        Get a specific voicemail message by ID.

        Args:
            message_id: The message ID
        """
        return await self._make_request(
            "GET",
            f"/restapi/v1.0/account/~/extension/~/message-store/{message_id}",
        )

    async def get_voicemail_content_url(self, content_uri: str) -> str:
        """
        Get the URL to download voicemail audio content with access token.

        Args:
            content_uri: The uri from the attachment object in message-store response
        """
        await self._ensure_authenticated()
        # Append access token for direct download
        if "?" in content_uri:
            return f"{content_uri}&access_token={self.access_token}"
        return f"{content_uri}?access_token={self.access_token}"

    async def find_voicemail_for_call(self, call_id: str, from_number: str, start_time: str) -> Optional[dict]:
        """
        Find the voicemail message associated with a call.

        Voicemails in the message-store don't have a direct link to call-log entries,
        so we match by phone number and approximate time.

        Args:
            call_id: The call ID (for logging)
            from_number: The caller's phone number
            start_time: The call start time (ISO format)

        Returns:
            The voicemail message dict with attachments, or None if not found
        """
        from datetime import datetime, timedelta

        try:
            # Parse the call start time
            if start_time.endswith("Z"):
                call_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                call_time = datetime.fromisoformat(start_time)

            # Search for voicemails within a window around the call time
            # Voicemail creation time might be slightly after call start
            date_from = call_time - timedelta(minutes=5)
            date_to = call_time + timedelta(minutes=30)

            result = await self.get_voicemail_messages(
                date_from=date_from,
                date_to=date_to,
                per_page=50,
            )

            # Normalize the from_number for matching
            from_digits = "".join(c for c in from_number if c.isdigit())
            if len(from_digits) == 11 and from_digits.startswith("1"):
                from_digits = from_digits[1:]  # Remove US country code

            for message in result.get("records", []):
                msg_from = message.get("from", {}).get("phoneNumber", "")
                msg_digits = "".join(c for c in msg_from if c.isdigit())
                if len(msg_digits) == 11 and msg_digits.startswith("1"):
                    msg_digits = msg_digits[1:]

                if from_digits == msg_digits:
                    logger.info(f"Found voicemail message {message.get('id')} for call {call_id}")
                    return message

            logger.warning(f"No voicemail message found for call {call_id} from {from_number}")
            return None

        except Exception as e:
            logger.error(f"Error finding voicemail for call {call_id}: {e}")
            return None


# Singleton instance
_client: Optional[RingCentralClient] = None


def get_ringcentral_client() -> RingCentralClient:
    """Get the RingCentral client singleton."""
    global _client
    if _client is None:
        _client = RingCentralClient()
    return _client
