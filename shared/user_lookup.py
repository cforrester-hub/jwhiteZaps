"""User mapping lookup utilities.

Provides functions to look up user information across different systems
(Deputy, RingCentral, etc.) using the shared user_mappings.json file.
"""

import json
from pathlib import Path
from typing import Optional

# Load mappings from JSON file
_MAPPINGS_FILE = Path(__file__).parent / "user_mappings.json"
_users: list[dict] = []


def _load_mappings() -> list[dict]:
    """Load user mappings from JSON file (cached)."""
    global _users
    if not _users:
        with open(_MAPPINGS_FILE) as f:
            data = json.load(f)
            _users = data.get("users", [])
    return _users


def get_all_users() -> list[dict]:
    """Get all user mappings."""
    return _load_mappings()


def find_by_deputy_id(deputy_id: str) -> Optional[dict]:
    """Find user by Deputy Employee ID."""
    for user in _load_mappings():
        if user.get("deputy_id") == str(deputy_id):
            return user
    return None


def find_by_ringcentral_member_id(member_id: str) -> Optional[dict]:
    """Find user by RingCentral Member ID."""
    for user in _load_mappings():
        if user.get("ringcentral_member_id") == str(member_id):
            return user
    return None


def find_by_ringcentral_extension_id(extension_id: str) -> Optional[dict]:
    """Find user by RingCentral Extension ID."""
    for user in _load_mappings():
        if user.get("ringcentral_extension_id") == str(extension_id):
            return user
    return None


def find_by_name(name: str, exact: bool = True) -> Optional[dict]:
    """Find user by name.

    Args:
        name: The name to search for
        exact: If True, match exactly. If False, match if name contains the search string.
    """
    for user in _load_mappings():
        user_name = user.get("name", "")
        if exact:
            if user_name.lower() == name.lower():
                return user
        else:
            if name.lower() in user_name.lower():
                return user
    return None


def reload_mappings() -> None:
    """Force reload of mappings from file."""
    global _users
    _users = []
    _load_mappings()
