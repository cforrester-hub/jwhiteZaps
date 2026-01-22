"""
Outgoing Call Workflow - Replaces the Zapier "Outgoing Call" ZAP

This workflow:
1. Polls RingCentral for outgoing calls (cron-based)
2. For each call, searches AgencyZoom for matching customers/leads by phone
3. If a match is found:
   - Uploads the call recording to DigitalOcean Spaces
   - Gets the RingSense AI summary (or generates one via LLM as fallback)
   - Creates a note in AgencyZoom with call details and summary
4. Tracks processed calls to avoid duplicates
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from . import register_workflow, TriggerType, is_processed, mark_processed
from ..http_client import ringcentral, agencyzoom, storage, transcription

logger = logging.getLogger(__name__)

# Minimum age for calls before processing (allows time for recording to be available)
CALL_PROCESSING_DELAY_MINUTES = 15


def is_call_too_recent(call: dict) -> bool:
    """Check if a call ended too recently to process (recording may not be ready)."""
    start_time = call.get("start_time", "")
    duration = call.get("duration", 0)

    if not start_time:
        return False  # Can't determine, allow processing

    try:
        # Parse the start time and add duration to get end time
        call_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        call_end = call_start + timedelta(seconds=duration)

        # Check if call ended less than CALL_PROCESSING_DELAY_MINUTES ago
        min_process_time = datetime.now(call_end.tzinfo) - timedelta(minutes=CALL_PROCESSING_DELAY_MINUTES)
        return call_end > min_process_time
    except (ValueError, TypeError):
        return False  # Can't parse, allow processing


def format_phone_for_display(phone: str, include_country_code: bool = False) -> str:
    """Format a phone number for display in notes."""
    # Remove non-digit characters
    digits = "".join(c for c in phone if c.isdigit())

    # Format as (XXX) XXX-XXXX for 10-digit US numbers
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits[0] == "1":
        if include_country_code:
            return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
        else:
            return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    return phone


def format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable format."""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        if secs:
            return f"{minutes}m {secs}s"
        return f"{minutes} minutes"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def is_internal_call(call: dict) -> bool:
    """
    Check if a call is internal (extension-to-extension).

    Internal calls have both parties as internal extensions, identified by:
    - Both from_extension_id and to_extension_id being set, OR
    - Both phone numbers being short (less than 10 digits, typical for extensions)
    """
    from_ext_id = call.get("from_extension_id")
    to_ext_id = call.get("to_extension_id")

    # If both have extension IDs, it's an internal call
    if from_ext_id and to_ext_id:
        return True

    # Also check phone number length - internal extensions are usually short
    from_number = call.get("from_number", "")
    to_number = call.get("to_number", "")

    # Strip non-digits to get the actual number length
    from_digits = "".join(c for c in from_number if c.isdigit())
    to_digits = "".join(c for c in to_number if c.isdigit())

    # External US numbers are 10-11 digits, internal extensions are typically 3-4 digits
    from_is_internal = len(from_digits) < 7
    to_is_internal = len(to_digits) < 7

    return from_is_internal and to_is_internal


def format_datetime_for_display(iso_datetime: str) -> str:
    """Format ISO datetime string for display in Pacific time."""
    if not iso_datetime:
        return "Unknown"
    try:
        # Parse ISO format (UTC) and convert to Pacific time
        dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        pacific = ZoneInfo("America/Los_Angeles")
        dt_pacific = dt.astimezone(pacific)
        return dt_pacific.strftime("%m/%d/%Y %I:%M %p")
    except (ValueError, AttributeError):
        return iso_datetime[:19] if iso_datetime else "Unknown"


def build_note_content(
    call_data: dict,
    direction: str = "Outbound",
    recording_url: Optional[str] = None,
    recording_urls: Optional[list] = None,
    ai_summary: Optional[str] = None,
    action_items: Optional[list] = None,
) -> str:
    """
    Build the note content for AgencyZoom using HTML format.

    Matches the Zapier template format with call information and recording details.

    Args:
        call_data: Dict containing call information under "call" key
        direction: "Outbound" or "Inbound"
        recording_url: Single recording URL (legacy, for backwards compatibility)
        recording_urls: List of (url, extension_name) tuples for all recording segments
        ai_summary: AI-generated summary of the call
        action_items: List of action items extracted from the call
    """
    call = call_data.get("call", {})

    # Determine the "other party" based on direction
    if direction == "Outbound":
        other_party = format_phone_for_display(call.get("to_number", "Unknown"))
    else:
        other_party = format_phone_for_display(call.get("from_number", "Unknown"))

    from_number = format_phone_for_display(call.get("from_number", "Unknown"))
    to_number = format_phone_for_display(call.get("to_number", "Unknown"))
    from_name = call.get("from_name")
    to_name = call.get("to_name")
    result = call.get("result", "Unknown")
    duration = format_duration(call.get("duration", 0))
    date_time = format_datetime_for_display(call.get("start_time"))
    recording_id = call.get("recording_id", "N/A")
    call_id = call.get("id", "Unknown")

    # Format from/to with extension name if available
    from_display = f"{from_number} ({from_name})" if from_name else from_number
    to_display = f"{to_number} ({to_name})" if to_name else to_number

    # Build HTML note matching Zapier template style
    # Header line: emoji + direction - other party - result
    header = f"📞 {direction} - {other_party} - {result}"

    # Build the HTML table - full width, no gaps
    html = f'''{header}<table style="width:100%;border-collapse:collapse;margin:0;padding:0;border-spacing:0;"><tr><td style="width:60%;vertical-align:top;background:#fff6e5;padding:10px;box-sizing:border-box;"><strong>CALL INFORMATION</strong><div>📅 <b>Date & Time:</b> {date_time}</div><div>👤 <b>From:</b> {from_display}</div><div>👤 <b>To:</b> {to_display}</div><div>⏱️ <b>Duration:</b> {duration}</div><div>📋 <b>Result:</b> {result}</div>'''

    # Add AI summary if available
    if ai_summary:
        html += f'''<div style="margin-top:10px;padding-top:10px;border-top:1px solid #ddd;"><strong>📝 AI SUMMARY</strong><div>{ai_summary}</div></div>'''

    # Add action items if available
    if action_items:
        html += '''<div style="margin-top:10px;padding-top:10px;border-top:1px solid #ddd;"><strong>✅ ACTION ITEMS</strong><ul style="margin:5px 0;padding-left:20px;">'''
        for item in action_items:
            html += f'''<li>{item}</li>'''
        html += '''</ul></div>'''

    html += '''</td><td style="width:40%;vertical-align:top;background:#f5eaff;padding:10px;box-sizing:border-box;"><strong>RECORDING INFORMATION</strong>'''

    # Handle multiple recordings (transferred calls) or single recording
    if recording_urls and len(recording_urls) > 0:
        # Multiple recording segments
        if len(recording_urls) > 1:
            html += f'''<div>📞 <b>Call Segments:</b> {len(recording_urls)} (call was transferred)</div>'''

        for idx, (rec_url, ext_name) in enumerate(recording_urls, 1):
            if len(recording_urls) > 1:
                # Multiple segments - label each one
                label = f"Part {idx}"
                if ext_name:
                    label += f" ({ext_name})"
                html += f'''<div>🔗 <b>{label}:</b> <a href="{rec_url}" target="_blank">Play Recording</a></div>'''
            else:
                # Single recording
                html += f'''<div>💾 <b>Recording ID:</b> {recording_id}</div><div>🔗 <b>Recording Link:</b> <a href="{rec_url}" target="_blank">Play Recording</a></div>'''

        html += f'''<div style="margin-top:10px;font-size:0.9em;color:#666;"><b>Call ID:</b> {call_id}</div>'''
    elif recording_url:
        # Legacy single recording URL (backwards compatibility)
        html += f'''<div>💾 <b>Recording ID:</b> {recording_id}</div><div>🔗 <b>Recording Link:</b> <a href="{recording_url}" target="_blank">Play Recording</a></div><div style="margin-top:10px;font-size:0.9em;color:#666;"><b>Call ID:</b> {call_id}</div>'''
    else:
        html += f'''<div>No recording available</div><div style="margin-top:10px;font-size:0.9em;color:#666;"><b>Call ID:</b> {call_id}</div>'''

    html += '''</td></tr></table>'''

    return html


async def process_single_call(call: dict) -> dict:
    """
    Process a single outgoing call.

    Returns a dict with the processing result.
    """
    call_id = call.get("id")
    to_number = call.get("to_number")

    logger.info(f"Processing call {call_id} to {to_number}")

    # Search AgencyZoom for customer/lead by phone number
    try:
        search_result = await agencyzoom.search_by_phone(to_number)
    except Exception as e:
        logger.error(f"Failed to search AgencyZoom: {e}")
        return {"status": "error", "reason": f"AgencyZoom search failed: {e}"}

    customers = search_result.get("customers", [])
    leads = search_result.get("leads", [])

    if not customers and not leads:
        logger.info(f"No match found in AgencyZoom for {to_number}, skipping")
        return {"status": "skipped", "reason": "no_match"}

    logger.info(f"Found {len(customers)} customers and {len(leads)} leads for {to_number}")

    # Get call details including all recordings and AI insights
    recording_urls = []  # List of (url, extension_name) tuples for all segments
    ai_summary = None
    action_items = []

    # Check if call has any recordings (could be multiple for transferred calls)
    has_recordings = call.get("recording_id") or call.get("recordings")

    if has_recordings:
        try:
            # Get full call details with AI insights
            call_details = await ringcentral.get_call_details(
                call_id,
                include_recording=True,
                include_ai_insights=True,
            )

            # Process all recordings (may be multiple for transferred calls)
            all_recordings = call_details.get("recordings", [])

            # Fallback to single recording if recordings array not available
            if not all_recordings:
                single_rec = call_details.get("recording")
                if single_rec:
                    all_recordings = [single_rec]

            logger.info(f"Call {call_id} has {len(all_recordings)} recording segment(s)")

            # Get recording info from call summary for extension names
            call_recording_infos = call.get("recordings", [])

            for rec_index, recording_info in enumerate(all_recordings):
                if recording_info and recording_info.get("content_url"):
                    content_url = recording_info.get("content_url")
                    content_type = recording_info.get("content_type", "audio/mpeg")
                    rec_id = recording_info.get("recording_id", f"rec{rec_index}")

                    # Get extension name from call recording info if available
                    extension_name = None
                    if rec_index < len(call_recording_infos):
                        extension_name = call_recording_infos[rec_index].get("extension_name")

                    # Determine file extension
                    ext = "mp3"
                    if "wav" in content_type:
                        ext = "wav"
                    elif "ogg" in content_type:
                        ext = "ogg"

                    # Build filename with date and segment index
                    call_date = call.get("start_time", "")[:10].replace("-", "/")
                    if len(all_recordings) > 1:
                        filename = f"{call_id}_part{rec_index + 1}.{ext}"
                    else:
                        filename = f"{call_id}.{ext}"
                    folder = f"recordings/{call_date}"

                    try:
                        upload_result = await storage.upload_from_url(
                            url=content_url,
                            filename=filename,
                            folder=folder,
                            content_type=content_type,
                            public=True,
                        )
                        rec_url = upload_result.get("url")
                        recording_urls.append((rec_url, extension_name))
                        logger.info(f"Uploaded recording segment {rec_index + 1} to {rec_url}")
                    except Exception as e:
                        logger.error(f"Failed to upload recording segment {rec_index + 1}: {e}")

            # Try RingSense first for AI summary (uses first/primary recording)
            ai_insights = call_details.get("ai_insights")
            if ai_insights and ai_insights.get("available"):
                ai_summary = ai_insights.get("summary")

            # If no RingSense summary, use transcription service on first recording
            if not ai_summary and all_recordings:
                first_rec = all_recordings[0]
                first_content_url = first_rec.get("content_url") if first_rec else None

                if first_content_url:
                    logger.info("RingSense not available, using transcription service")
                    try:
                        # Build context for better summarization
                        context = f"Outbound call to {to_number}"
                        if len(all_recordings) > 1:
                            context += f" (call had {len(all_recordings)} segments due to transfer)"

                        transcription_result = await transcription.transcribe_and_summarize(
                            audio_url=first_content_url,
                            context=context,
                            filename=f"{call_id}.mp3",
                        )
                        ai_summary = transcription_result.get("summary")
                        action_items = transcription_result.get("action_items", [])
                        logger.info(f"Transcription complete: {len(ai_summary or '')} char summary, {len(action_items)} action items")
                    except Exception as e:
                        logger.warning(f"Transcription service failed, continuing without summary: {e}")

        except Exception as e:
            logger.error(f"Failed to get call details: {e}")

    # Build the note content
    note_content = build_note_content(
        call_data={"call": call},
        direction="Outbound",
        recording_urls=recording_urls,
        ai_summary=ai_summary,
        action_items=action_items,
    )

    # Create notes in AgencyZoom
    # Priority: Create note on CUSTOMER if they exist (even if also a lead)
    # Only create note on LEAD if they are NOT also a customer
    notes_created = 0

    if customers:
        # Person is a customer - create note(s) on customer record(s) only
        for customer in customers:
            customer_id = customer.get("id")
            if customer_id:
                try:
                    await agencyzoom.create_customer_note(
                        customer_id=str(customer_id),
                        content=note_content,
                    )
                    notes_created += 1
                    logger.info(f"Created note for customer {customer_id}")
                except Exception as e:
                    logger.error(f"Failed to create customer note: {e}")
    elif leads:
        # Person is only a lead (not a customer) - create note(s) on lead record(s)
        for lead in leads:
            lead_id = lead.get("id")
            if lead_id:
                try:
                    await agencyzoom.create_lead_note(
                        lead_id=str(lead_id),
                        content=note_content,
                    )
                    notes_created += 1
                    logger.info(f"Created note for lead {lead_id}")
                except Exception as e:
                    logger.error(f"Failed to create lead note: {e}")

    return {
        "status": "success",
        "customers_matched": len(customers),
        "leads_matched": len(leads),
        "notes_created": notes_created,
        "recording_uploaded": recording_url is not None,
        "has_ai_summary": ai_summary is not None,
    }


@register_workflow(
    name="outgoing_call",
    description="Sync outgoing calls from RingCentral to AgencyZoom",
    trigger_type=TriggerType.CRON,
    cron_expression="1,6,11,16,21,26,31,36,41,46,51,56 * * * *",  # Every 5 minutes at :01
    enabled=True,
)
async def run():
    """
    Main workflow entry point.

    Fetches recent outgoing calls and processes any that haven't been handled yet.
    """
    logger.info("Starting outgoing_call workflow")

    # Fetch calls from the last 48 hours
    # We process with a delay to ensure recordings are available
    try:
        calls_response = await ringcentral.get_calls(
            date_from=(datetime.utcnow() - timedelta(days=2)).isoformat() + "Z",
            date_to=datetime.utcnow().isoformat() + "Z",
            direction="Outbound",
            per_page=100,
        )
    except Exception as e:
        logger.error(f"Failed to fetch calls from RingCentral: {e}")
        return {"items_processed": 0, "error": str(e)}

    calls = calls_response.get("calls", [])
    logger.info(f"Found {len(calls)} outgoing calls")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for call in calls:
        call_id = call.get("id")

        # Skip if already processed
        if await is_processed(call_id, "outgoing_call"):
            logger.debug(f"Call {call_id} already processed, skipping")
            continue

        # Skip calls that ended too recently (recording may not be ready)
        if is_call_too_recent(call):
            logger.debug(f"Call {call_id} ended less than {CALL_PROCESSING_DELAY_MINUTES} minutes ago, will process later")
            continue

        # Skip internal (extension-to-extension) calls
        if is_internal_call(call):
            logger.debug(f"Call {call_id} is internal call, skipping")
            await mark_processed(call_id, "outgoing_call", success=True, details="Skipped: internal call")
            skipped_count += 1
            continue

        # Skip calls with no result or failed calls
        result = call.get("result", "")
        if result not in ("Accepted", "Call connected"):
            logger.debug(f"Call {call_id} has result '{result}', skipping")
            await mark_processed(call_id, "outgoing_call", success=True, details=f"Skipped: {result}")
            skipped_count += 1
            continue

        # Process the call
        try:
            # IMPORTANT: Mark as "processing" BEFORE creating notes to prevent duplicates
            # If we crash after creating notes but before marking processed, we'd create
            # duplicate notes on the next run. By marking first, we ensure idempotency.
            await mark_processed(
                call_id,
                "outgoing_call",
                success=True,
                details="processing",
            )

            process_result = await process_single_call(call)

            if process_result["status"] == "success":
                # Update with final result
                await mark_processed(
                    call_id,
                    "outgoing_call",
                    success=True,
                    details=f"notes={process_result['notes_created']}",
                )
                processed_count += 1
            elif process_result["status"] == "skipped" and process_result.get("reason") == "no_match":
                # No customer/lead found in AgencyZoom
                await mark_processed(
                    call_id,
                    "outgoing_call",
                    success=True,
                    details="no_match_in_agencyzoom",
                )
                skipped_count += 1
            else:
                # Error occurred - mark as failed so we can track it, but don't retry
                # to avoid creating duplicate notes
                await mark_processed(
                    call_id,
                    "outgoing_call",
                    success=False,
                    details=f"error: {process_result.get('reason', 'Unknown')}",
                )
                error_count += 1

        except Exception as e:
            # Exception occurred - the call is already marked as "processing"
            # so it won't be retried. Log the error for debugging.
            logger.error(f"Error processing call {call_id}: {e}")
            try:
                await mark_processed(
                    call_id,
                    "outgoing_call",
                    success=False,
                    details=f"exception: {str(e)[:200]}",
                )
            except Exception:
                pass  # If we can't update the status, at least it's marked as processing
            error_count += 1

    logger.info(
        f"Workflow complete: processed={processed_count}, skipped={skipped_count}, errors={error_count}"
    )

    return {
        "items_processed": processed_count,
        "items_skipped": skipped_count,
        "items_errored": error_count,
        "total_calls": len(calls),
    }
