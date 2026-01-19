"""Parse Deputy timesheet webhook payloads to determine clock actions.

Ported from JavaScript implementation. Handles:
- Clock in/out detection
- Break start/end detection
- Dedupe key generation
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TimesheetAction(str, Enum):
    """Possible timesheet actions."""

    CLOCK_IN = "clock_in"
    CLOCK_OUT = "clock_out"
    BREAK_START = "break_start"
    BREAK_END = "break_end"
    IGNORE = "ignore"


class DesiredDndStatus(str, Enum):
    """RingCentral DND status to set."""

    TAKE_ALL_CALLS = "TakeAllCalls"
    DO_NOT_ACCEPT_DEPARTMENT_CALLS = "DoNotAcceptDepartmentCalls"


@dataclass
class BreakSlot:
    """Represents a break slot from the timesheet."""

    start: Optional[int]  # Unix timestamp
    end: Optional[int]  # Unix timestamp, None if in progress
    state: str  # e.g., "in progress", "finished"
    type_name: str  # e.g., "Meal Break", "Rest Break"
    break_type: str  # "M" or "R"


@dataclass
class ParsedTimesheetEvent:
    """Result of parsing a timesheet webhook."""

    action: TimesheetAction
    desired_dnd_status: Optional[DesiredDndStatus]
    timesheet_id: Optional[int]
    employee_id: Optional[int]
    event_unix: Optional[int]
    dedupe_key: Optional[str]
    reason: str
    topic: Optional[str] = None
    debug_break: Optional[BreakSlot] = None


def _to_number(value: Any) -> Optional[int]:
    """Convert value to integer, or None if not possible."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        s = str(value).strip()
        if not s:
            return None
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _to_bool(value: Any) -> Optional[bool]:
    """Convert value to boolean, or None if not possible."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def _get_timesheet_object(payload: dict) -> Optional[dict]:
    """Extract the timesheet object from various payload formats."""
    if not payload:
        return None

    # Try payload.data (array or object)
    if "data" in payload:
        data = payload["data"]
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        if isinstance(data, dict):
            return data

    # Try other common wrappers
    if "result" in payload:
        return payload["result"]
    if "record" in payload:
        return payload["record"]

    # Check if payload itself is the timesheet
    if any(k in payload for k in ("Id", "StartTime", "IsInProgress")):
        return payload

    return None


def _get_most_recent_break_slot(slots: Any) -> Optional[BreakSlot]:
    """Extract the most recent break slot from the Slots array."""
    if not isinstance(slots, list) or len(slots) == 0:
        return None

    break_slots = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue

        # Filter for break type "B"
        str_type = str(slot.get("strType", "")).upper()
        if str_type != "B":
            continue

        start = _to_number(slot.get("intUnixStart"))
        if start is None:
            continue

        break_slots.append(
            BreakSlot(
                start=start,
                end=_to_number(slot.get("intUnixEnd")),
                state=str(slot.get("strState", "")).lower(),
                type_name=str(slot.get("strTypeName", "")),
                break_type=str(
                    slot.get("mixedActivity", {}).get("strBreakType", "")
                    if isinstance(slot.get("mixedActivity"), dict)
                    else ""
                ),
            )
        )

    if not break_slots:
        return None

    # Sort by start time and return the most recent
    break_slots.sort(key=lambda b: b.start or 0)
    return break_slots[-1]


def _is_break_in_progress(break_slot: Optional[BreakSlot]) -> bool:
    """Check if a break slot is currently in progress."""
    if not break_slot:
        return False
    if break_slot.end is None:
        return True
    if "in progress" in break_slot.state or "started" in break_slot.state:
        return True
    return False


def _fnv1a_hash(s: str) -> str:
    """FNV-1a 32-bit hash, matching the JavaScript implementation."""
    h = 0x811C9DC5
    for char in s:
        h ^= ord(char)
        h = ((h * 0x01000193) & 0xFFFFFFFF)
    return format(h, "08x")


def _generate_dedupe_key(
    timesheet_id: int, action: TimesheetAction, event_unix: int
) -> str:
    """Generate a unique dedupe key for an event."""
    base = f"{timesheet_id}|{action.value}|{event_unix}"
    hash_val = _fnv1a_hash(base)

    prefix_map = {
        TimesheetAction.CLOCK_IN: "tci",
        TimesheetAction.CLOCK_OUT: "tco",
        TimesheetAction.BREAK_START: "tbs",
        TimesheetAction.BREAK_END: "tbe",
    }
    prefix = prefix_map.get(action, "evt")

    return f"{prefix}_{hash_val}"


def parse_timesheet_webhook(payload: dict) -> ParsedTimesheetEvent:
    """
    Parse a Deputy timesheet webhook payload.

    Determines the action (clock_in, clock_out, break_start, break_end)
    and generates a dedupe key for the event.

    Args:
        payload: The webhook payload from Deputy

    Returns:
        ParsedTimesheetEvent with action details
    """
    ts_obj = _get_timesheet_object(payload)

    if not ts_obj:
        return ParsedTimesheetEvent(
            action=TimesheetAction.IGNORE,
            desired_dnd_status=None,
            timesheet_id=None,
            employee_id=None,
            event_unix=None,
            dedupe_key=None,
            reason="No timesheet object found in payload",
        )

    timesheet_id = _to_number(ts_obj.get("Id"))
    employee_id = _to_number(ts_obj.get("Employee"))
    is_in_progress = _to_bool(ts_obj.get("IsInProgress"))
    start_time = _to_number(ts_obj.get("StartTime"))
    end_time = _to_number(ts_obj.get("EndTime"))

    created = ts_obj.get("Created")
    modified = ts_obj.get("Modified")

    # Webhook metadata
    webhook_ts = _to_number(payload.get("timestamp"))
    topic = str(payload.get("topic", "")).strip()

    action = TimesheetAction.IGNORE
    desired_dnd_status = None
    reason = "No actionable event detected"
    debug_break = None

    # Get latest break slot
    latest_break_slot = _get_most_recent_break_slot(ts_obj.get("Slots"))

    # 1) Clock out (strong signal)
    if is_in_progress is False and end_time:
        action = TimesheetAction.CLOCK_OUT
        desired_dnd_status = DesiredDndStatus.DO_NOT_ACCEPT_DEPARTMENT_CALLS
        reason = "IsInProgress=false and EndTime present"

    # 2) Break start / end (while shift in progress)
    elif is_in_progress is True and latest_break_slot:
        debug_break = latest_break_slot

        if _is_break_in_progress(latest_break_slot):
            action = TimesheetAction.BREAK_START
            desired_dnd_status = DesiredDndStatus.DO_NOT_ACCEPT_DEPARTMENT_CALLS
            reason = "Most recent break slot is in progress"
        elif latest_break_slot.end:
            seconds_since_end = (
                abs(webhook_ts - latest_break_slot.end)
                if webhook_ts
                else None
            )
            if seconds_since_end is not None and seconds_since_end <= 180:
                action = TimesheetAction.BREAK_END
                desired_dnd_status = DesiredDndStatus.TAKE_ALL_CALLS
                reason = f"Most recent break ended recently (within {seconds_since_end}s)"

    # 3) Clock in
    if action == TimesheetAction.IGNORE and is_in_progress is True and start_time:
        is_insert = topic.lower() == "timesheet.insert"
        created_equals_modified = (
            created and modified and str(created) == str(modified)
        )

        if is_insert or created_equals_modified:
            action = TimesheetAction.CLOCK_IN
            desired_dnd_status = DesiredDndStatus.TAKE_ALL_CALLS
            reason = (
                "Timesheet.Insert with IsInProgress=true"
                if is_insert
                else "Created equals Modified (creation event) with IsInProgress=true"
            )

    # Determine event timestamp for dedupe
    event_unix = None
    if action == TimesheetAction.CLOCK_IN:
        event_unix = start_time
    elif action == TimesheetAction.CLOCK_OUT:
        event_unix = end_time
    elif action == TimesheetAction.BREAK_START and latest_break_slot:
        event_unix = latest_break_slot.start
    elif action == TimesheetAction.BREAK_END and latest_break_slot:
        event_unix = latest_break_slot.end

    # Generate dedupe key
    dedupe_key = None
    if (
        timesheet_id
        and action != TimesheetAction.IGNORE
        and event_unix
    ):
        dedupe_key = _generate_dedupe_key(timesheet_id, action, event_unix)

    logger.info(
        f"Parsed timesheet webhook: action={action.value}, "
        f"employee={employee_id}, dedupe_key={dedupe_key}, reason={reason}"
    )

    return ParsedTimesheetEvent(
        action=action,
        desired_dnd_status=desired_dnd_status,
        timesheet_id=timesheet_id,
        employee_id=employee_id,
        event_unix=event_unix,
        dedupe_key=dedupe_key,
        reason=reason,
        topic=topic or None,
        debug_break=debug_break,
    )
