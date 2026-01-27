"""
Voicemail Workflow - Creates tasks for voicemail calls

This workflow:
1. Polls RingCentral for voicemail calls (cron-based)
2. For each voicemail, searches AgencyZoom for matching customers/leads by phone
3. Transcribes the voicemail message
4. Creates a task in AgencyZoom:
   - If customer found: assign to customer's primary CSR
   - If only lead found: assign to lead's primary producer
   - If no match: assign to fallback customer (34401683) and their CSR
5. Tracks processed calls to avoid duplicates
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from . import register_workflow, TriggerType, is_processed, mark_processed, get_processed_ids
from .outgoing_call import (
    format_phone_for_display,
    format_duration,
    is_call_too_recent,
    CALL_PROCESSING_DELAY_MINUTES,
)
from ..http_client import ringcentral, agencyzoom, storage, transcription

logger = logging.getLogger(__name__)

# Fallback customer ID for voicemails with no match
FALLBACK_CUSTOMER_ID = 34401683
# Fallback CSR ID (from customer 34401683's policy)
FALLBACK_CSR_ID = 110493


def build_task_title(caller_name: str, caller_number: str) -> str:
    """Build the task title for a voicemail."""
    phone_display = format_phone_for_display(caller_number)
    if caller_name and caller_name.strip():
        return f"Voicemail from {caller_name.strip()} - {phone_display}"
    return f"Voicemail from {phone_display}"


def build_task_content(
    call: dict,
    recording_url: Optional[str] = None,
    transcript: Optional[str] = None,
) -> str:
    """
    Build the task content/comments for AgencyZoom.

    Matches the Zapier template format.
    """
    from zoneinfo import ZoneInfo

    from_number = format_phone_for_display(call.get("from_number", "Unknown"))
    from_name = call.get("from_name", "").strip() or "Unknown"
    start_time = call.get("start_time", "")
    duration = format_duration(call.get("duration", 0))

    # Format the received time in Pacific timezone
    received = "Unknown"
    if start_time:
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            # Convert UTC to Pacific time
            pacific = ZoneInfo("America/Los_Angeles")
            dt_pacific = dt.astimezone(pacific)
            received = dt_pacific.strftime("%m/%d/%Y %I:%M %p")
        except (ValueError, AttributeError):
            received = start_time[:19] if start_time else "Unknown"

    # Build HTML content matching Zapier template
    html = '<h1><u><b>NOTES:</b></u></h1>\n'
    html += '<ul><li>AZ -- Task Created</li></ul>\n'
    html += '<br /><br />\n'

    if recording_url:
        html += f'<a href="{recording_url}" target="_blank">Click here to play the audio file</a> --> {recording_url}\n'
    else:
        html += '<p>No recording available</p>\n'

    html += '<br />\n'
    html += '<h1><u><b>TRANSCRIPT:</b></u></h1>\n'

    if transcript:
        html += f'{transcript}\n'
    else:
        html += '<p>Transcription not available</p>\n'

    html += '<br /><br />\n'
    html += f'<b>From:</b> {from_name} - {from_number}\n'
    html += '<br />\n'
    html += f'<b>Received:</b> {received}<br />\n'
    html += f'<b>Length:</b> {duration}\n'

    return html


async def process_single_voicemail(call: dict) -> dict:
    """
    Process a single voicemail call.

    Returns a dict with the processing result.
    """
    call_id = call.get("id")
    from_number = call.get("from_number")
    from_name = call.get("from_name", "").strip()
    start_time = call.get("start_time", "")

    logger.info(f"Processing voicemail {call_id} from {from_number}")

    # Search AgencyZoom for customer/lead by phone number
    # If search fails or phone number is invalid, we'll use the fallback
    customers = []
    leads = []

    # Only search if we have a valid phone number (at least 7 digits)
    phone_digits = "".join(c for c in (from_number or "") if c.isdigit())
    if len(phone_digits) >= 7:
        try:
            search_result = await agencyzoom.search_by_phone(from_number)
            customers = search_result.get("customers", [])
            leads = search_result.get("leads", [])
        except Exception as e:
            logger.warning(f"AgencyZoom search failed for {from_number}, using fallback: {e}")

    # Determine assignment
    customer_id = None
    lead_id = None
    assignee_id = None

    if customers:
        # Assign to customer's primary CSR
        customer = customers[0]
        customer_id = customer.get("id")
        logger.info(f"Found customer {customer_id} for {from_number}")

        try:
            assignee_id = await agencyzoom.get_customer_csr_id(customer_id)
            logger.info(f"Customer CSR ID: {assignee_id}")
        except Exception as e:
            logger.warning(f"Failed to get CSR for customer {customer_id}: {e}")

    elif leads:
        # Assign to lead's primary producer
        lead = leads[0]
        lead_id = lead.get("id")
        logger.info(f"Found lead {lead_id} for {from_number}")

        try:
            assignee_id = await agencyzoom.get_lead_producer_id(lead_id)
            logger.info(f"Lead producer ID: {assignee_id}")
        except Exception as e:
            logger.warning(f"Failed to get producer for lead {lead_id}: {e}")

    # Fallback if no match or no assignee found
    if not assignee_id:
        logger.info(f"Using fallback customer {FALLBACK_CUSTOMER_ID} and CSR {FALLBACK_CSR_ID}")
        customer_id = FALLBACK_CUSTOMER_ID
        assignee_id = FALLBACK_CSR_ID
        lead_id = None  # Clear lead_id if using fallback

    # Get voicemail audio from message-store (NOT from call-log recording)
    # Voicemails are stored separately in RingCentral's message-store API
    recording_url = None
    transcript = None
    content_url = None

    try:
        # Find the voicemail message associated with this call
        # The message-store has the actual audio attachment
        voicemail_info = await ringcentral.find_voicemail_for_call(
            call_id=call_id,
            from_number=from_number,
            start_time=start_time,
        )

        content_url = voicemail_info.get("content_url")
        content_type = voicemail_info.get("content_type", "audio/mpeg")
        vm_duration = voicemail_info.get("duration")

        if content_url:
            logger.info(f"Found voicemail audio for call {call_id}, duration: {vm_duration}s")

            # Determine file extension from content type
            ext = "mp3"
            if "wav" in content_type:
                ext = "wav"
            elif "ogg" in content_type:
                ext = "ogg"

            # Build filename with date
            call_date = start_time[:10].replace("-", "/") if start_time else "unknown"
            filename = f"{call_id}.{ext}"
            folder = f"voicemails/{call_date}"

            # Upload voicemail audio to storage
            try:
                upload_result = await storage.upload_from_url(
                    url=content_url,
                    filename=filename,
                    folder=folder,
                    content_type=content_type,
                    public=True,
                )
                recording_url = upload_result.get("url")
                logger.info(f"Uploaded voicemail to {recording_url}")
            except Exception as e:
                logger.error(f"Failed to upload voicemail: {e}")

            # Transcribe the voicemail
            try:
                transcription_result = await transcription.transcribe_and_summarize(
                    audio_url=content_url,
                    context=f"Voicemail from {from_name or from_number}",
                    filename=filename,
                )
                transcript = transcription_result.get("transcript")
                logger.info(f"Transcription complete: {len(transcript or '')} chars")
            except Exception as e:
                logger.warning(f"Transcription failed: {e}")
        else:
            logger.warning(f"Voicemail found but no content URL for call {call_id}")

    except Exception as e:
        # Voicemail not found in message-store - this can happen if:
        # 1. The voicemail was deleted
        # 2. The voicemail hasn't synced yet (try again later)
        # 3. The phone number matching failed
        logger.warning(f"Could not find voicemail audio for call {call_id}: {e}")

    # Build task content
    task_title = build_task_title(from_name, from_number)
    task_content = build_task_content(
        call=call,
        recording_url=recording_url,
        transcript=transcript,
    )

    # Use the call start time as the due datetime
    due_datetime = start_time if start_time else datetime.utcnow().isoformat() + "Z"

    # Create the task
    try:
        result = await agencyzoom.create_task(
            title=task_title,
            due_datetime=due_datetime,
            assignee_id=assignee_id,
            customer_id=customer_id,
            lead_id=lead_id,
            comments=task_content,
            task_type="call",
            duration=15,
            time_specific=True,
        )
        logger.info(f"Created task for voicemail {call_id}")
    except Exception as e:
        logger.error(f"Failed to create task: {e}")
        return {"status": "error", "reason": f"Task creation failed: {e}"}

    return {
        "status": "success",
        "customer_id": customer_id,
        "lead_id": lead_id,
        "assignee_id": assignee_id,
        "has_recording": recording_url is not None,
        "has_transcript": transcript is not None,
        "used_fallback": customer_id == FALLBACK_CUSTOMER_ID,
    }


@register_workflow(
    name="voicemail",
    description="Create tasks for voicemail calls from RingCentral",
    trigger_type=TriggerType.CRON,
    cron_expression="2,7,12,17,22,27,32,37,42,47,52,57 * * * *",  # Every 5 minutes at :02
    enabled=True,
)
async def run():
    """
    Main workflow entry point.

    Fetches recent voicemail calls and creates tasks for any that haven't been handled yet.
    """
    logger.info("Starting voicemail workflow")

    # Fetch calls from the last 4 hours
    # We process with a 15-min delay to ensure recordings are available
    try:
        calls_response = await ringcentral.get_calls(
            date_from=(datetime.utcnow() - timedelta(hours=4)).isoformat() + "Z",
            date_to=datetime.utcnow().isoformat() + "Z",
            direction="Inbound",
            per_page=100,
        )
    except Exception as e:
        logger.error(f"Failed to fetch calls from RingCentral: {e}")
        return {"items_processed": 0, "error": str(e)}

    calls = calls_response.get("calls", [])
    logger.info(f"Found {len(calls)} inbound calls")

    # Filter for voicemail calls only
    voicemail_calls = [c for c in calls if c.get("result") == "Voicemail"]
    logger.info(f"Found {len(voicemail_calls)} voicemail calls")

    # Batch check which voicemails are already processed (single DB query instead of N queries)
    all_voicemail_ids = [call.get("id") for call in voicemail_calls]
    already_processed = await get_processed_ids(all_voicemail_ids, "voicemail")
    logger.info(f"Already processed: {len(already_processed)} of {len(voicemail_calls)} voicemails")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for call in voicemail_calls:
        call_id = call.get("id")

        # Skip if already processed (fast set lookup, no DB query)
        if call_id in already_processed:
            continue

        # Skip voicemails that ended too recently (recording may not be ready)
        if is_call_too_recent(call):
            logger.debug(f"Voicemail {call_id} ended less than {CALL_PROCESSING_DELAY_MINUTES} minutes ago, will process later")
            continue

        # Process the voicemail
        try:
            process_result = await process_single_voicemail(call)

            if process_result["status"] == "success":
                await mark_processed(
                    call_id,
                    "voicemail",
                    success=True,
                    details=f"customer={process_result.get('customer_id')},assignee={process_result.get('assignee_id')}",
                )
                processed_count += 1
            else:
                # Error occurred - DO NOT mark as processed, will retry on next run
                logger.warning(
                    f"Voicemail {call_id} had error, will retry: {process_result.get('reason', 'Unknown')}"
                )
                error_count += 1

        except Exception as e:
            # Exception occurred - DO NOT mark as processed, will retry on next run
            logger.error(f"Error processing voicemail {call_id}, will retry: {e}")
            error_count += 1

    logger.info(
        f"Workflow complete: processed={processed_count}, skipped={skipped_count}, errors={error_count}"
    )

    return {
        "items_processed": processed_count,
        "items_skipped": skipped_count,
        "items_errored": error_count,
        "total_voicemails": len(voicemail_calls),
    }
