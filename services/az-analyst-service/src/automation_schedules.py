"""Pipeline automation schedules and note source classification.

Encodes per-pipeline, per-stage automated touchpoints so the coaching
endpoint can distinguish system-generated messages from producer activity.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class Channel:
    SMS = "sms"
    EMAIL = "email"
    TASK_CALL = "task_call"
    TASK_INTERNAL = "task_internal"
    TASK_MAIL = "task_mail"


class TouchpointType:
    AUTOMATED = "automated_message"
    PRODUCER_TASK = "producer_task"


@dataclass(frozen=True)
class ScheduledTouchpoint:
    business_day: int
    channel: str
    touchpoint_type: str
    scheduled_hour: int = 10
    description: str = ""


@dataclass(frozen=True)
class StageSchedule:
    stage_name: str
    touchpoints: tuple
    auto_unenrollment: bool = True


@dataclass(frozen=True)
class PipelineSchedule:
    pipeline_name: str
    stages: dict
    has_any_sms: bool = True


# ---------------------------------------------------------------------------
# NPL Internet / Protege Home schedule
# ---------------------------------------------------------------------------

_NPL_INTERNET_NEW = StageSchedule(
    stage_name="New",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.SMS, TouchpointType.AUTOMATED, 9, "Speed-to-lead SMS"),
        ScheduledTouchpoint(1, Channel.EMAIL, TouchpointType.AUTOMATED, 9, "Roof age info email"),
        ScheduledTouchpoint(1, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Day 1 call x3"),
        ScheduledTouchpoint(1, Channel.SMS, TouchpointType.AUTOMATED, 15, "Afternoon follow-up SMS"),
        ScheduledTouchpoint(2, Channel.SMS, TouchpointType.AUTOMATED, 9, "Day 2 SMS"),
        ScheduledTouchpoint(2, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 14, "4th call attempt"),
        ScheduledTouchpoint(3, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Why a local agency email"),
        ScheduledTouchpoint(4, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 9, "5th call attempt"),
        ScheduledTouchpoint(6, Channel.SMS, TouchpointType.AUTOMATED, 10, "Casual check-in SMS"),
        ScheduledTouchpoint(8, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Still shopping email"),
        ScheduledTouchpoint(11, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "6th call attempt"),
        ScheduledTouchpoint(15, Channel.SMS, TouchpointType.AUTOMATED, 10, "Final check-in SMS"),
        ScheduledTouchpoint(22, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "We're here email"),
    ),
)

_NPL_INTERNET_CONTACTED = StageSchedule(
    stage_name="Contacted",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 0, "Lead Tracker"),
        ScheduledTouchpoint(18, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Shot clock heads up"),
    ),
)

_NPL_INTERNET_QUOTED = StageSchedule(
    stage_name="Quoted",
    touchpoints=(
        ScheduledTouchpoint(30, Channel.SMS, TouchpointType.AUTOMATED, 10, "Quote still here SMS"),
        ScheduledTouchpoint(32, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Checking in email"),
        ScheduledTouchpoint(36, Channel.SMS, TouchpointType.AUTOMATED, 10, "Happy to adjust SMS"),
        ScheduledTouchpoint(40, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Why a real agency email"),
        ScheduledTouchpoint(42, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Shot clock heads up"),
        ScheduledTouchpoint(43, Channel.SMS, TouchpointType.AUTOMATED, 10, "We're here SMS"),
    ),
)

_NPL_INTERNET_FSD_THIS = StageSchedule(
    stage_name="FSD This Folio",
    touchpoints=(
        ScheduledTouchpoint(30, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Shot clock heads up"),
    ),
)

_NPL_INTERNET_FSD_NEXT = StageSchedule(
    stage_name="FSD Next Folio",
    touchpoints=(
        ScheduledTouchpoint(30, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Shot clock heads up"),
    ),
)

_NPL_INTERNET_WAITING = StageSchedule(
    stage_name="Waiting on Carrier",
    touchpoints=(
        ScheduledTouchpoint(3, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Follow up with carrier"),
        ScheduledTouchpoint(8, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Carrier status check"),
        ScheduledTouchpoint(15, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Escalation check"),
        ScheduledTouchpoint(18, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Shot clock heads up"),
    ),
)

_NPL_INTERNET_SCHEDULE = PipelineSchedule(
    pipeline_name="1 NPL Internet",
    stages={
        "New": _NPL_INTERNET_NEW,
        "Contacted": _NPL_INTERNET_CONTACTED,
        "Quoted": _NPL_INTERNET_QUOTED,
        "FSD This Folio": _NPL_INTERNET_FSD_THIS,
        "FSD Next Folio": _NPL_INTERNET_FSD_NEXT,
        "Waiting on Carrier": _NPL_INTERNET_WAITING,
    },
    has_any_sms=True,
)

# ---------------------------------------------------------------------------
# NPL Call/Walk-In schedule
# ---------------------------------------------------------------------------

_CALL_WALK_CONTACTED = StageSchedule(
    stage_name="Contacted",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 0, "Tracking task"),
    ),
)

_CALL_WALK_QUOTED = StageSchedule(
    stage_name="Quoted",
    touchpoints=(
        ScheduledTouchpoint(2, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Quote review call"),
        ScheduledTouchpoint(3, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Got everything email"),
        ScheduledTouchpoint(8, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Follow-up call"),
        ScheduledTouchpoint(8, Channel.EMAIL, TouchpointType.AUTOMATED, 14, "Why customers stick email"),
        ScheduledTouchpoint(15, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "We're here email"),
    ),
)

_CALL_WALK_FSD_THIS = StageSchedule(
    stage_name="FSD This Folio",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.EMAIL, TouchpointType.AUTOMATED, 0, "What happens next email"),
        ScheduledTouchpoint(8, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Mid-period check-in"),
        ScheduledTouchpoint(8, Channel.EMAIL, TouchpointType.AUTOMATED, 14, "Process update email"),
        ScheduledTouchpoint(15, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Pre-close check-in"),
        ScheduledTouchpoint(21, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Ready to wrap up email"),
        ScheduledTouchpoint(26, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Final Folio check-in"),
    ),
)

_CALL_WALK_FSD_NEXT = StageSchedule(
    stage_name="FSD Next Folio",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.EMAIL, TouchpointType.AUTOMATED, 0, "No rush email"),
        ScheduledTouchpoint(11, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Value content email"),
        ScheduledTouchpoint(15, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Mid-wait check-in"),
        ScheduledTouchpoint(15, Channel.TASK_MAIL, TouchpointType.PRODUCER_TASK, 0, "Postcard / handwritten note"),
        ScheduledTouchpoint(26, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Window coming up email"),
        ScheduledTouchpoint(29, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Transition call"),
    ),
)

_CALL_WALK_WAITING = StageSchedule(
    stage_name="Waiting on Carrier",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.EMAIL, TouchpointType.AUTOMATED, 0, "Application submitted email"),
        ScheduledTouchpoint(4, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Carrier follow-up"),
        ScheduledTouchpoint(6, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Status update email"),
        ScheduledTouchpoint(8, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Carrier + customer update"),
        ScheduledTouchpoint(11, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Haven't forgotten email"),
        ScheduledTouchpoint(15, Channel.TASK_CALL, TouchpointType.PRODUCER_TASK, 10, "Escalation check"),
    ),
)

_CALL_WALK_HOME_SEARCHING = StageSchedule(
    stage_name="Home Searching",
    touchpoints=(
        ScheduledTouchpoint(1, Channel.EMAIL, TouchpointType.AUTOMATED, 0, "We'll be here email"),
        ScheduledTouchpoint(30, Channel.EMAIL, TouchpointType.AUTOMATED, 10, "Still looking email"),
        ScheduledTouchpoint(60, Channel.TASK_INTERNAL, TouchpointType.PRODUCER_TASK, 10, "Producer review"),
    ),
    auto_unenrollment=False,
)

_NPL_CALL_WALK_IN_SCHEDULE = PipelineSchedule(
    pipeline_name="1 NPL Call/Walk In",
    stages={
        "Contacted": _CALL_WALK_CONTACTED,
        "Info Needed": _CALL_WALK_CONTACTED,
        "Quoted": _CALL_WALK_QUOTED,
        "FSD This Folio": _CALL_WALK_FSD_THIS,
        "FSD Next Folio": _CALL_WALK_FSD_NEXT,
        "Waiting on Carrier": _CALL_WALK_WAITING,
        "Home Searching": _CALL_WALK_HOME_SEARCHING,
    },
    has_any_sms=False,
)

# ---------------------------------------------------------------------------
# Pipeline name -> schedule lookup
# ---------------------------------------------------------------------------

PIPELINE_SCHEDULES: dict[str, PipelineSchedule] = {
    "1 NPL Internet": _NPL_INTERNET_SCHEDULE,
    "Protege Home": _NPL_INTERNET_SCHEDULE,
    "1 NPL Call/Walk In": _NPL_CALL_WALK_IN_SCHEDULE,
}

# ---------------------------------------------------------------------------
# Business day math
# ---------------------------------------------------------------------------


def _business_day_number(start: date, target: date) -> int:
    """1-indexed business day of target relative to start (both inclusive).

    Same day = day 1, next business day = day 2, etc.
    Weekends are skipped.
    """
    if target < start:
        return 0
    if target == start:
        return 1
    count = 1
    current = start
    while current < target:
        current += timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


def _parse_to_pacific(date_str: str | None) -> datetime | None:
    """Parse a date string to a Pacific-aware datetime."""
    if not date_str:
        return None
    try:
        s = date_str.strip()
        if "T" in s:
            s = s.replace("T", " ")
        if "." in s:
            s = s.split(".")[0]
        if len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=PACIFIC)
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=PACIFIC)
    except (ValueError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Stage history reconstruction
# ---------------------------------------------------------------------------

_MOVE_STAGE_RE = re.compile(
    r"moved from\s*<a[^>]*>([^<]+)</a>\s*to\s*<a[^>]*>([^<]+)</a>",
    re.IGNORECASE,
)


@dataclass
class StageSpan:
    stage_name: str
    entered_at: datetime
    exited_at: datetime | None = None


def _parse_move_stage_body(body: str | None) -> tuple[str | None, str | None]:
    """Extract (from_stage, to_stage) from MOVE_STAGE note body HTML.

    Body format: 'moved from <a>Pipeline | Stage</a> to <a>Pipeline | Stage</a>'
    Returns stage names only (strips pipeline prefix).
    """
    if not body:
        return None, None
    m = _MOVE_STAGE_RE.search(body)
    if not m:
        return None, None
    from_raw = m.group(1).strip()
    to_raw = m.group(2).strip()
    from_stage = from_raw.split("|")[-1].strip() if "|" in from_raw else from_raw
    to_stage = to_raw.split("|")[-1].strip() if "|" in to_raw else to_raw
    return from_stage, to_stage


def reconstruct_stage_history(
    lead_create_date: str | None,
    lead_enter_stage_date: str | None,
    current_stage_name: str | None,
    move_stage_notes: list,
) -> list[StageSpan]:
    """Build chronological stage history from MOVE_STAGE notes.

    Falls back to a single span if no MOVE_STAGE notes exist.
    """
    created_dt = _parse_to_pacific(lead_create_date)
    if not created_dt:
        return []

    spans: list[StageSpan] = []

    sorted_notes = sorted(move_stage_notes, key=lambda n: n.create_date or "")

    for note in sorted_notes:
        note_dt = _parse_to_pacific(note.create_date)
        if not note_dt:
            continue
        from_stage, to_stage = _parse_move_stage_body(note.body)
        if not to_stage:
            continue

        if spans:
            spans[-1].exited_at = note_dt
        elif from_stage:
            spans.append(StageSpan(stage_name=from_stage, entered_at=created_dt, exited_at=note_dt))

        spans.append(StageSpan(stage_name=to_stage, entered_at=note_dt))

    if not spans:
        stage = current_stage_name or "Unknown"
        enter_dt = _parse_to_pacific(lead_enter_stage_date) or created_dt
        spans.append(StageSpan(stage_name=stage, entered_at=enter_dt))

    return spans


def _stage_at_time(stage_history: list[StageSpan], dt: datetime) -> StageSpan | None:
    """Find which stage span contains the given datetime."""
    for span in reversed(stage_history):
        if dt >= span.entered_at:
            if span.exited_at is None or dt < span.exited_at:
                return span
    if stage_history:
        return stage_history[0]
    return None


# ---------------------------------------------------------------------------
# Unenrollment detection
# ---------------------------------------------------------------------------

UNENROLL_NOTE_TYPES = {"auto_unenroll_automation", "unenroll_automation"}
ENROLL_NOTE_TYPES = {"auto_enroll_automation", "enroll_automation"}


def detect_unenrollment_periods(
    all_notes: list,
    pipeline_schedule: PipelineSchedule,
    stage_history: list[StageSpan],
) -> list[tuple[datetime, datetime | None]]:
    """Find periods where automation was unenrolled.

    Returns list of (unenroll_time, re_enroll_time|None) tuples.
    A lead can be unenrolled and re-enrolled multiple times.
    """
    periods: list[tuple[datetime, datetime | None]] = []

    for note in sorted(all_notes, key=lambda n: n.create_date or ""):
        ntype = (note.note_type or "").lower().strip()
        note_dt = _parse_to_pacific(note.create_date)
        if not note_dt:
            continue

        span = _stage_at_time(stage_history, note_dt)
        if span:
            stage_sched = pipeline_schedule.stages.get(span.stage_name)
            if stage_sched and not stage_sched.auto_unenrollment:
                continue

        if ntype in UNENROLL_NOTE_TYPES:
            if not periods or periods[-1][1] is not None:
                periods.append((note_dt, None))
        elif ntype in ENROLL_NOTE_TYPES:
            if periods and periods[-1][1] is None:
                periods = periods[:-1] + [(periods[-1][0], note_dt)]

    return periods


def _is_unenrolled_at(periods: list[tuple[datetime, datetime | None]], dt: datetime) -> bool:
    """Check if automation was unenrolled at a given time."""
    for start, end in periods:
        if dt >= start and (end is None or dt < end):
            return True
    return False


# ---------------------------------------------------------------------------
# Note source classification
# ---------------------------------------------------------------------------

def _note_channel(note_type: str | None) -> str | None:
    """Map AZ note_type to our Channel constant."""
    nt = (note_type or "").lower().strip()
    if nt == "email":
        return Channel.EMAIL
    if nt == "text":
        return Channel.SMS
    if nt in ("comment", "general", "call"):
        return "call"
    if nt == "task":
        return "task"
    return None


# TCPA opt-out keywords — inbound SMS containing only these words are
# carrier-level unsubscribes, not customer conversations.
SMS_OPT_OUT_KEYWORDS = {"stop", "unsubscribe", "cancel", "end", "quit"}


def _is_sms_opt_out(note) -> bool:
    """Check if an inbound TEXT note is a TCPA opt-out (e.g. 'STOP')."""
    if (note.note_type or "").lower().strip() != "text":
        return False
    body = (note.body or "").strip()
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", body).strip().lower()
    return clean in SMS_OPT_OUT_KEYWORDS


@dataclass
class NoteSourceResult:
    source: str          # "automated" | "producer" | "sms_opt_out" | "unknown_source"
    confidence: str      # "high" | "medium" | "low"
    reason: str


def classify_note_source(
    note,
    pipeline_schedule: PipelineSchedule | None,
    stage_history: list[StageSpan],
    unenroll_periods: list[tuple[datetime, datetime | None]],
) -> NoteSourceResult:
    """Classify a single note as automated, producer-driven, or unknown."""

    note_type = (note.note_type or "").lower().strip()
    note_dt = _parse_to_pacific(note.create_date)

    if not note_dt:
        return NoteSourceResult("unknown_source", "low", "unparseable timestamp")

    # Explicitly tagged automation note types
    if note_type in UNENROLL_NOTE_TYPES | ENROLL_NOTE_TYPES | {"auto_enroll_automation", "auto_unenroll_automation"}:
        return NoteSourceResult("automated", "high", f"system event: {note_type}")
    if "auto" in note_type:
        return NoteSourceResult("automated", "high", f"auto-tagged: {note_type}")

    # Non-message note types
    if note_type in ("tag", "move_stage"):
        return NoteSourceResult("unknown_source", "high", f"system event: {note_type}")

    # No pipeline schedule -> can't classify
    if not pipeline_schedule:
        return NoteSourceResult("unknown_source", "low", "no pipeline schedule available")

    channel = _note_channel(note_type)
    if not channel:
        return NoteSourceResult("unknown_source", "low", f"unrecognized note type: {note_type}")

    # SMS opt-out (e.g. "STOP") — not a conversation, not producer activity
    if channel == Channel.SMS and _is_sms_opt_out(note):
        return NoteSourceResult("sms_opt_out", "high", "TCPA opt-out keyword — lead unsubscribed from SMS, not a contact")

    # Calls are always producer-driven (automation only sends SMS/email)
    if channel == "call":
        return NoteSourceResult("producer", "high", "calls are always producer-initiated")

    # Tasks: creation is automated, completion is producer activity
    # In practice the note represents the task existing, not completion
    if channel == "task":
        return NoteSourceResult("unknown_source", "medium", "task note — creation automated, completion is producer")

    # SMS on a pipeline with no SMS automation
    if channel == Channel.SMS and not pipeline_schedule.has_any_sms:
        return NoteSourceResult("producer", "high", "no SMS automation in this pipeline")

    # Check unenrollment
    if _is_unenrolled_at(unenroll_periods, note_dt):
        return NoteSourceResult("producer", "high", "automation was unenrolled at this time")

    # Find which stage the lead was in
    span = _stage_at_time(stage_history, note_dt)
    if not span:
        return NoteSourceResult("unknown_source", "low", "no stage context for this timestamp")

    stage_sched = pipeline_schedule.stages.get(span.stage_name)
    if not stage_sched:
        return NoteSourceResult("unknown_source", "low", f"no schedule for stage: {span.stage_name}")

    # Check if this stage has any automated messages for this channel
    automated_touchpoints = [
        tp for tp in stage_sched.touchpoints
        if tp.touchpoint_type == TouchpointType.AUTOMATED and tp.channel == channel
    ]
    if not automated_touchpoints:
        return NoteSourceResult("producer", "high", f"no automated {channel} in {span.stage_name}")

    # Compute business day in stage
    bday = _business_day_number(span.entered_at.date(), note_dt.date())
    note_hour = note_dt.hour

    # Try to match against scheduled automation
    for tp in automated_touchpoints:
        day_diff = abs(tp.business_day - bday)
        hour_diff = abs(tp.scheduled_hour - note_hour)

        if day_diff == 0 and hour_diff <= 2:
            return NoteSourceResult("automated", "high", f"matches {tp.description} (day {tp.business_day}, ~{tp.scheduled_hour}:00)")
        if day_diff == 0 and hour_diff <= 4:
            return NoteSourceResult("automated", "medium", f"likely {tp.description} (day {tp.business_day}, hour drift)")
        if day_diff <= 1 and hour_diff <= 2:
            return NoteSourceResult("automated", "medium", f"likely {tp.description} (day {tp.business_day}±1)")
        if day_diff <= 2 and hour_diff <= 3:
            return NoteSourceResult("automated", "low", f"possible {tp.description} (day {tp.business_day}±2)")

    # No automation match — but this stage has automation for this channel.
    # If it's outside any scheduled window, it's likely producer-driven.
    return NoteSourceResult("producer", "medium", f"no automation match in {span.stage_name} day {bday}")


# ---------------------------------------------------------------------------
# Batch classification entry point
# ---------------------------------------------------------------------------

def _init_counts() -> dict:
    return {
        "automated_outbound_emails": 0,
        "automated_outbound_texts": 0,
        "producer_outbound_emails": 0,
        "producer_outbound_texts": 0,
        "producer_outbound_calls": 0,
        "producer_inbound_emails": 0,
        "producer_inbound_texts": 0,
        "producer_inbound_calls": 0,
        "producer_task_updates": 0,
        "sms_opt_outs": 0,
        "unknown_source_count": 0,
    }


def _update_counts(counts: dict, note, result: NoteSourceResult, note_classification: dict):
    """Update counts based on note source classification and direction."""
    nt = (note.note_type or "").lower().strip()
    direction = note_classification.get("direction")

    if result.source == "sms_opt_out":
        counts["sms_opt_outs"] += 1
    elif result.source == "automated":
        if nt == "email":
            counts["automated_outbound_emails"] += 1
        elif nt == "text":
            counts["automated_outbound_texts"] += 1
    elif result.source == "producer":
        if nt == "email":
            if direction == "inbound":
                counts["producer_inbound_emails"] += 1
            else:
                counts["producer_outbound_emails"] += 1
        elif nt == "text":
            if direction == "inbound":
                counts["producer_inbound_texts"] += 1
            else:
                counts["producer_outbound_texts"] += 1
        elif nt in ("comment", "general", "call"):
            if direction == "inbound":
                counts["producer_inbound_calls"] += 1
            else:
                counts["producer_outbound_calls"] += 1
        elif nt == "task":
            counts["producer_task_updates"] += 1
    else:
        counts["unknown_source_count"] += 1


def classify_lead_notes(
    lead_workflow_name: str | None,
    lead_pipeline_id: str | None,
    lead_create_date: str | None,
    lead_enter_stage_date: str | None,
    current_stage_name: str | None,
    all_notes: list,
    period_notes: list,
    classify_note_func,
    pipelines_map: dict | None = None,
) -> dict:
    """Classify all period notes for a single lead.

    Args:
        lead_workflow_name: Pipeline name from lead record
        lead_pipeline_id: Pipeline ID from lead record
        lead_create_date: Lead creation date string
        lead_enter_stage_date: Current stage entry date string
        current_stage_name: Current stage name
        all_notes: All notes for this lead (lifetime, for stage reconstruction)
        period_notes: Notes in the analysis period to classify
        classify_note_func: The existing _classify_note(note) function from analysis.py
        pipelines_map: Optional pipeline_id -> name lookup
    """
    pipeline_name = lead_workflow_name
    if not pipeline_name and pipelines_map and lead_pipeline_id:
        pipeline_name = pipelines_map.get(lead_pipeline_id)

    pipeline_schedule = PIPELINE_SCHEDULES.get(pipeline_name) if pipeline_name else None

    if not pipeline_schedule:
        classifications = []
        counts = _init_counts()
        for note in period_notes:
            classifications.append({
                "note_id": getattr(note, "id", None),
                "source": "unknown_source",
                "confidence": "low",
                "reason": f"no schedule for pipeline: {pipeline_name or 'unknown'}",
            })
            counts["unknown_source_count"] += 1
        return {
            "pipeline_schedule_available": False,
            "unenrollment_detected": False,
            "unenrollment_timestamp": None,
            "note_classifications": classifications,
            "counts": counts,
        }

    # Reconstruct stage history
    move_notes = [n for n in all_notes if (n.note_type or "").lower().strip() == "move_stage"]
    stage_history = reconstruct_stage_history(
        lead_create_date, lead_enter_stage_date, current_stage_name, move_notes,
    )

    # Detect unenrollment periods
    unenroll_periods = detect_unenrollment_periods(all_notes, pipeline_schedule, stage_history)

    classifications = []
    counts = _init_counts()

    for note in period_notes:
        result = classify_note_source(note, pipeline_schedule, stage_history, unenroll_periods)

        existing_class = classify_note_func(note) if classify_note_func else {}

        classifications.append({
            "note_id": getattr(note, "id", None),
            "source": result.source,
            "confidence": result.confidence,
            "reason": result.reason,
        })
        _update_counts(counts, note, result, existing_class)

    first_unenroll = unenroll_periods[0][0] if unenroll_periods else None

    return {
        "pipeline_schedule_available": True,
        "unenrollment_detected": bool(unenroll_periods),
        "unenrollment_timestamp": first_unenroll.isoformat() if first_unenroll else None,
        "note_classifications": classifications,
        "counts": counts,
    }
