"""Employee clock status management with WebSocket broadcasting.

Tracks employee clock-in/out and break status, broadcasts updates to connected clients.
"""

import asyncio
import logging
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import WebSocket
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ClockStatus(str, Enum):
    """Employee clock status values."""

    CLOCKED_IN = "clocked_in"
    CLOCKED_OUT = "clocked_out"
    ON_BREAK = "on_break"
    UNKNOWN = "unknown"


class EmployeeStatus(BaseModel):
    """Status of a single employee."""

    employee_id: str
    name: str
    clock_status: ClockStatus
    last_updated: str  # ISO format
    ringcentral_extension_id: Optional[str] = None


class StatusUpdate(BaseModel):
    """A status update message for WebSocket broadcast."""

    type: str = "status_update"
    employee_id: str
    name: str
    clock_status: ClockStatus
    timestamp: str


class AllStatusMessage(BaseModel):
    """Message containing all employee statuses."""

    type: str = "all_statuses"
    employees: list[EmployeeStatus]
    timestamp: str


class EmployeeStatusManager:
    """Manages employee statuses and WebSocket connections."""

    def __init__(self):
        # In-memory status storage: employee_id -> EmployeeStatus
        self._statuses: dict[str, EmployeeStatus] = {}
        # Connected WebSocket clients: websocket -> client_id
        self._connections: dict[WebSocket, str] = {}
        # Valid API keys for authentication
        self._api_keys: set[str] = set()
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    def add_api_key(self, key: str) -> None:
        """Add a valid API key for authentication."""
        self._api_keys.add(key)

    def validate_api_key(self, key: str) -> bool:
        """Check if an API key is valid."""
        return key in self._api_keys

    def generate_api_key(self) -> str:
        """Generate a new API key and register it."""
        key = f"ess_{secrets.token_urlsafe(32)}"
        self._api_keys.add(key)
        return key

    async def register_connection(self, websocket: WebSocket, client_id: str) -> None:
        """Register a new WebSocket connection."""
        async with self._lock:
            self._connections[websocket] = client_id
            logger.info(f"Client registered: {client_id} (total: {len(self._connections)})")

    async def unregister_connection(self, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection."""
        async with self._lock:
            client_id = self._connections.pop(websocket, None)
            if client_id:
                logger.info(f"Client unregistered: {client_id} (total: {len(self._connections)})")

    async def update_status(
        self,
        employee_id: str,
        name: str,
        clock_status: ClockStatus,
        ringcentral_extension_id: Optional[str] = None,
    ) -> None:
        """Update an employee's status and broadcast to all connected clients."""
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            self._statuses[employee_id] = EmployeeStatus(
                employee_id=employee_id,
                name=name,
                clock_status=clock_status,
                last_updated=now,
                ringcentral_extension_id=ringcentral_extension_id,
            )

        logger.info(f"Status updated: {name} ({employee_id}) -> {clock_status.value}")

        # Broadcast update to all connected clients
        update_message = StatusUpdate(
            employee_id=employee_id,
            name=name,
            clock_status=clock_status,
            timestamp=now,
        )
        await self._broadcast(update_message.model_dump_json())

    async def get_all_statuses(self) -> list[EmployeeStatus]:
        """Get all employee statuses."""
        async with self._lock:
            return list(self._statuses.values())

    async def get_status(self, employee_id: str) -> Optional[EmployeeStatus]:
        """Get status for a specific employee."""
        async with self._lock:
            return self._statuses.get(employee_id)

    async def initialize_employee(
        self,
        employee_id: str,
        name: str,
        ringcentral_extension_id: Optional[str] = None,
        clock_status: ClockStatus = ClockStatus.UNKNOWN,
    ) -> None:
        """Initialize an employee in the status tracker without broadcasting."""
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            if employee_id not in self._statuses:
                self._statuses[employee_id] = EmployeeStatus(
                    employee_id=employee_id,
                    name=name,
                    clock_status=clock_status,
                    last_updated=now,
                    ringcentral_extension_id=ringcentral_extension_id,
                )

    async def send_all_statuses(self, websocket: WebSocket) -> None:
        """Send all current statuses to a specific client."""
        statuses = await self.get_all_statuses()
        message = AllStatusMessage(
            employees=statuses,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        try:
            await websocket.send_text(message.model_dump_json())
        except Exception as e:
            logger.error(f"Failed to send statuses to client: {e}")

    async def _broadcast(self, message: str) -> None:
        """Broadcast a message to all connected clients."""
        async with self._lock:
            connections = list(self._connections.keys())

        if not connections:
            return

        # Send to all clients concurrently
        tasks = []
        for websocket in connections:
            tasks.append(self._send_to_client(websocket, message))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_to_client(self, websocket: WebSocket, message: str) -> None:
        """Send a message to a single client, handling errors."""
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.warning(f"Failed to send to client, removing: {e}")
            await self.unregister_connection(websocket)

    @property
    def connection_count(self) -> int:
        """Get the number of connected clients."""
        return len(self._connections)


# Global status manager instance
status_manager = EmployeeStatusManager()
