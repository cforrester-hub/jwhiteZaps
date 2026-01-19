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

    async def get_extensions(self) -> list:
        """
        Get all extensions in the account.

        Returns a list of extension info dicts.
        """
        result = await self._make_request(
            "GET",
            "/restapi/v1.0/account/~/extension",
            params={"perPage": 500, "status": "Enabled"},
        )
        return result.get("records", [])

    async def get_voicemail_messages(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        per_page: int = 100,
        page: int = 1,
        extension_id: str = "~",
    ) -> dict:
        """
        Fetch voicemail messages from the message store for a specific extension.

        This is different from call logs - voicemail audio is accessed
        through the message-store API, not the call-log recording API.

        Args:
            date_from: Start date for filtering messages
            date_to: End date for filtering messages
            per_page: Number of records per page (max 250)
            page: Page number
            extension_id: Extension ID (use "~" for current user)
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
            f"/restapi/v1.0/account/~/extension/{extension_id}/message-store",
            params=params,
        )

    async def get_all_voicemail_messages(
        self,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        per_page: int = 100,
    ) -> list:
        """
        Fetch voicemail messages from ALL extensions in the account.

        Iterates through all enabled extensions and collects their voicemails.

        Args:
            date_from: Start date for filtering messages
            date_to: End date for filtering messages
            per_page: Number of records per page per extension

        Returns:
            List of all voicemail messages across all extensions
        """
        all_messages = []

        try:
            extensions = await self.get_extensions()
            logger.info(f"Found {len(extensions)} extensions to search for voicemails")

            for ext in extensions:
                ext_id = ext.get("id")
                ext_name = ext.get("name", "Unknown")

                try:
                    result = await self.get_voicemail_messages(
                        date_from=date_from,
                        date_to=date_to,
                        per_page=per_page,
                        extension_id=str(ext_id),
                    )
                    messages = result.get("records", [])
                    if messages:
                        logger.info(f"Found {len(messages)} voicemails for extension {ext_name} ({ext_id})")
                        # Add extension info to each message for context
                        for msg in messages:
                            msg["_extension_id"] = ext_id
                            msg["_extension_name"] = ext_name
                        all_messages.extend(messages)
                except Exception as e:
                    # Some extensions may not have message-store access
                    logger.debug(f"Could not get voicemails for extension {ext_name}: {e}")

        except Exception as e:
            logger.error(f"Error getting extensions: {e}")

        return all_messages

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

    async def get_voicemail_message_by_extension(self, extension_id: str, message_id: str) -> dict:
        """
        Get a specific voicemail message from a specific extension.

        Args:
            extension_id: The extension ID that owns the voicemail
            message_id: The message ID
        """
        return await self._make_request(
            "GET",
            f"/restapi/v1.0/account/~/extension/{extension_id}/message-store/{message_id}",
        )

    async def find_voicemail_for_call(self, call_id: str, from_number: str, start_time: str) -> Optional[dict]:
        """
        Find the voicemail message associated with a call.

        First tries to get the voicemail directly from the call log's detailed legs
        (which include the message ID and extension ID). Falls back to searching
        across extensions if the direct method fails.

        Args:
            call_id: The call ID
            from_number: The caller's phone number (fallback for search)
            start_time: The call start time (fallback for search)

        Returns:
            The voicemail message dict with attachments, or None if not found
        """
        try:
            # First, try to get voicemail info directly from the call log
            # The detailed call log includes the message ID in the legs
            call_details = await self.get_call_with_details(call_id)

            legs = call_details.get("legs", [])
            for leg in legs:
                message_info = leg.get("message", {})
                if message_info.get("type") == "VoiceMail" and message_info.get("id"):
                    message_id = str(message_info.get("id"))
                    extension_info = leg.get("extension", {})
                    extension_id = str(extension_info.get("id", "~"))

                    logger.info(f"Found voicemail {message_id} in call log for call {call_id}, extension {extension_id}")

                    # Fetch the full voicemail message with attachments
                    try:
                        return await self.get_voicemail_message_by_extension(extension_id, message_id)
                    except Exception as e:
                        logger.warning(f"Could not fetch voicemail {message_id} from extension {extension_id}: {e}")

            # Fallback: search by phone number and time (slower but comprehensive)
            logger.info(f"No voicemail in call log legs, falling back to search for call {call_id}")
            return await self._search_voicemail_by_phone_and_time(call_id, from_number, start_time)

        except Exception as e:
            logger.error(f"Error finding voicemail for call {call_id}: {e}")
            return None

    async def _search_voicemail_by_phone_and_time(
        self, call_id: str, from_number: str, start_time: str
    ) -> Optional[dict]:
        """
        Fallback method: Search for voicemail by phone number and approximate time.
        Searches across all extensions.
        """
        from datetime import datetime, timedelta

        try:
            # Parse the call start time
            if start_time.endswith("Z"):
                call_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            else:
                call_time = datetime.fromisoformat(start_time)

            # Search window around call time
            date_from = call_time - timedelta(minutes=5)
            date_to = call_time + timedelta(minutes=30)

            # Search across ALL extensions
            all_messages = await self.get_all_voicemail_messages(
                date_from=date_from,
                date_to=date_to,
                per_page=50,
            )

            logger.info(f"Searching {len(all_messages)} voicemails for call {call_id} from {from_number}")

            # Normalize the from_number for matching
            from_digits = "".join(c for c in from_number if c.isdigit())
            if len(from_digits) == 11 and from_digits.startswith("1"):
                from_digits = from_digits[1:]

            for message in all_messages:
                msg_from = message.get("from", {}).get("phoneNumber", "")
                msg_digits = "".join(c for c in msg_from if c.isdigit())
                if len(msg_digits) == 11 and msg_digits.startswith("1"):
                    msg_digits = msg_digits[1:]

                if from_digits == msg_digits:
                    ext_name = message.get("_extension_name", "Unknown")
                    logger.info(f"Found voicemail {message.get('id')} for call {call_id} on extension {ext_name}")
                    return message

            logger.warning(f"No voicemail found for call {call_id} from {from_number}")
            return None

        except Exception as e:
            logger.error(f"Search voicemail error for call {call_id}: {e}")
            return None


# Singleton instance
_client: Optional[RingCentralClient] = None


def get_ringcentral_client() -> RingCentralClient:
    """Get the RingCentral client singleton."""
    global _client
    if _client is None:
        _client = RingCentralClient()
    return _client
