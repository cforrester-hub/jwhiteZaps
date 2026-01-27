"""
Incoming Call Workflow - Replaces the Zapier "Incoming Call" ZAP

This workflow:
1. Polls RingCentral for incoming calls (cron-based)
2. For each call, searches AgencyZoom for matching customers/leads by phone
3. If a match is found:
   - Uploads the call recording to DigitalOcean Spaces (if available)
   - Gets the RingSense AI summary (or generates one via LLM as fallback)
   - Creates a note in AgencyZoom with call details and summary
4. Tracks processed calls to avoid duplicates
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from . import register_workflow, TriggerType, is_processed, mark_processed, get_processed_ids
from .outgoing_call import (
    format_phone_for_display,
    format_duration,
    build_note_content,
    is_call_too_recent,
    is_internal_call,
    CALL_PROCESSING_DELAY_MINUTES,
)
from ..http_client import ringcentral, agencyzoom, storage, transcription

logger = logging.getLogger(__name__)


async def process_single_call(call: dict, mark_as_processed_callback=None) -> dict:
    """
    Process a single incoming call.

    Args:
        call: The call data dict from RingCentral
        mark_as_processed_callback: Optional async callback to mark the call as processed
            immediately after AgencyZoom confirms note creation. This prevents duplicates
            even if later steps fail.

    Returns a dict with the processing result.
    """
    call_id = call.get("id")
    from_number = call.get("from_number")

    logger.info(f"Processing incoming call {call_id} from {from_number}")

    # Search AgencyZoom for customer/lead by phone number (caller's number)
    try:
        search_result = await agencyzoom.search_by_phone(from_number)
    except Exception as e:
        logger.error(f"Failed to search AgencyZoom: {e}")
        return {"status": "error", "reason": f"AgencyZoom search failed: {e}"}

    customers = search_result.get("customers", [])
    leads = search_result.get("leads", [])

    if not customers and not leads:
        logger.info(f"No match found in AgencyZoom for {from_number}, skipping")
        return {"status": "skipped", "reason": "no_match"}

    logger.info(f"Found {len(customers)} customers and {len(leads)} leads for {from_number}")

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
                        context = f"Inbound call from {from_number}"
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

    # Build the note content (using "Inbound" direction)
    note_content = build_note_content(
        call_data={"call": call},
        direction="Inbound",
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
                    # CRITICAL: Mark as processed IMMEDIATELY after AZ confirms note creation
                    # This prevents duplicates even if later steps fail
                    if mark_as_processed_callback and notes_created == 1:
                        await mark_as_processed_callback()
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
                    # CRITICAL: Mark as processed IMMEDIATELY after AZ confirms note creation
                    # This prevents duplicates even if later steps fail
                    if mark_as_processed_callback and notes_created == 1:
                        await mark_as_processed_callback()
                except Exception as e:
                    logger.error(f"Failed to create lead note: {e}")

    return {
        "status": "success",
        "customers_matched": len(customers),
        "leads_matched": len(leads),
        "notes_created": notes_created,
        "recording_uploaded": len(recording_urls) > 0,
        "has_ai_summary": ai_summary is not None,
    }


@register_workflow(
    name="incoming_call",
    description="Sync incoming calls from RingCentral to AgencyZoom",
    trigger_type=TriggerType.CRON,
    cron_expression="0,5,10,15,20,25,30,35,40,45,50,55 * * * *",  # Every 5 minutes at :00
    enabled=True,
)
async def run():
    """
    Main workflow entry point.

    Fetches recent incoming calls and processes any that haven't been handled yet.
    """
    logger.info("Starting incoming_call workflow")

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
    logger.info(f"Found {len(calls)} incoming calls")

    # Batch check which calls are already processed (single DB query instead of N queries)
    all_call_ids = [call.get("id") for call in calls]
    already_processed = await get_processed_ids(all_call_ids, "incoming_call")
    logger.info(f"Already processed: {len(already_processed)} of {len(calls)} calls")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for call in calls:
        call_id = call.get("id")

        # Skip if already processed (fast set lookup, no DB query)
        if call_id in already_processed:
            continue

        # Skip calls that ended too recently (recording may not be ready)
        if is_call_too_recent(call):
            logger.debug(f"Call {call_id} ended less than {CALL_PROCESSING_DELAY_MINUTES} minutes ago, will process later")
            continue

        # Skip internal (extension-to-extension) calls
        if is_internal_call(call):
            logger.debug(f"Call {call_id} is internal call, skipping")
            await mark_processed(call_id, "incoming_call", success=True, details="Skipped: internal call")
            skipped_count += 1
            continue

        # Skip calls with no result or failed calls
        result = call.get("result", "")
        if result not in ("Accepted", "Call connected"):
            logger.debug(f"Call {call_id} has result '{result}', skipping")
            await mark_processed(call_id, "incoming_call", success=True, details=f"Skipped: {result}")
            skipped_count += 1
            continue

        # Process the call
        try:
            # Track if we've already marked this call as processed (via callback)
            call_marked_processed = False

            async def mark_call_processed():
                nonlocal call_marked_processed
                if not call_marked_processed:
                    await mark_processed(
                        call_id,
                        "incoming_call",
                        success=True,
                        details="note_created",
                    )
                    call_marked_processed = True
                    logger.info(f"Marked call {call_id} as processed immediately after AZ confirmation")

            process_result = await process_single_call(call, mark_as_processed_callback=mark_call_processed)

            if process_result["status"] == "success":
                # Update with final details if not already marked
                if not call_marked_processed:
                    await mark_processed(
                        call_id,
                        "incoming_call",
                        success=True,
                        details=f"notes={process_result['notes_created']}",
                    )
                else:
                    # Update the details with final note count (upsert will update existing)
                    await mark_processed(
                        call_id,
                        "incoming_call",
                        success=True,
                        details=f"notes={process_result['notes_created']}",
                    )
                processed_count += 1
            elif process_result["status"] == "skipped" and process_result.get("reason") == "no_match":
                # No customer/lead found in AgencyZoom - mark as processed so we don't keep checking
                await mark_processed(
                    call_id,
                    "incoming_call",
                    success=True,
                    details="no_match_in_agencyzoom",
                )
                skipped_count += 1
            else:
                # Error occurred - only retry if we haven't already created a note
                if call_marked_processed:
                    logger.warning(f"Call {call_id} had error after note was created, not retrying")
                    error_count += 1
                else:
                    logger.warning(
                        f"Call {call_id} had error, will retry: {process_result.get('reason', 'Unknown')}"
                    )
                    error_count += 1

        except Exception as e:
            # Exception occurred - DO NOT mark as processed, will retry on next run
            logger.error(f"Error processing call {call_id}, will retry: {e}")
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
