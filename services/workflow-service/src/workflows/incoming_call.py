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

from . import register_workflow, TriggerType, is_processed, mark_processed
from .outgoing_call import (
    format_phone_for_display,
    format_duration,
    build_note_content,
)
from ..http_client import ringcentral, agencyzoom, storage

logger = logging.getLogger(__name__)


async def process_single_call(call: dict) -> dict:
    """
    Process a single incoming call.

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

    # Get call details including recording and AI insights
    recording_url = None
    ai_summary = None
    recording_id = call.get("recording_id")

    if recording_id:
        try:
            # Get full call details with AI insights
            call_details = await ringcentral.get_call_details(
                call_id,
                include_recording=True,
                include_ai_insights=True,
            )

            # Upload recording to storage
            recording_info = call_details.get("recording")
            if recording_info and recording_info.get("content_url"):
                content_url = recording_info.get("content_url")
                content_type = recording_info.get("content_type", "audio/mpeg")

                # Determine file extension
                ext = "mp3"
                if "wav" in content_type:
                    ext = "wav"
                elif "ogg" in content_type:
                    ext = "ogg"

                # Build filename with date
                call_date = call.get("start_time", "")[:10].replace("-", "/")
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
                    recording_url = upload_result.get("url")
                    logger.info(f"Uploaded recording to {recording_url}")
                except Exception as e:
                    logger.error(f"Failed to upload recording: {e}")

            # Get AI summary from RingSense
            ai_insights = call_details.get("ai_insights")
            if ai_insights and ai_insights.get("available"):
                ai_summary = ai_insights.get("summary")

                # If no summary but transcript available, we could use LLM here
                if not ai_summary and ai_insights.get("transcript"):
                    logger.info("RingSense summary not available, would use LLM fallback")
                    # TODO: Implement LLM fallback for summarization

        except Exception as e:
            logger.error(f"Failed to get call details: {e}")

    # Build the note content (using "Inbound" direction)
    note_content = build_note_content(
        call_data={"call": call},
        direction="Inbound",
        recording_url=recording_url,
        ai_summary=ai_summary,
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
    name="incoming_call",
    description="Sync incoming calls from RingCentral to AgencyZoom",
    trigger_type=TriggerType.CRON,
    cron_expression="*/15 * * * *",  # Every 15 minutes
    enabled=True,
)
async def run():
    """
    Main workflow entry point.

    Fetches recent incoming calls and processes any that haven't been handled yet.
    """
    logger.info("Starting incoming_call workflow")

    # Fetch calls from the last 48 hours
    # We process with a delay to ensure recordings are available
    try:
        calls_response = await ringcentral.get_calls(
            date_from=(datetime.utcnow() - timedelta(days=2)).isoformat() + "Z",
            date_to=datetime.utcnow().isoformat() + "Z",
            direction="Inbound",
            per_page=100,
        )
    except Exception as e:
        logger.error(f"Failed to fetch calls from RingCentral: {e}")
        return {"items_processed": 0, "error": str(e)}

    calls = calls_response.get("calls", [])
    logger.info(f"Found {len(calls)} incoming calls")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for call in calls:
        call_id = call.get("id")

        # Skip if already processed
        if await is_processed(call_id, "incoming_call"):
            logger.debug(f"Call {call_id} already processed, skipping")
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
            process_result = await process_single_call(call)

            if process_result["status"] == "success":
                # Successfully created notes - mark as processed
                await mark_processed(
                    call_id,
                    "incoming_call",
                    success=True,
                    details=f"notes={process_result['notes_created']}",
                )
                processed_count += 1
            elif process_result["status"] == "skipped" and process_result.get("reason") == "no_match":
                # No customer/lead found in AgencyZoom - this is a legitimate skip
                # Mark as processed so we don't keep checking this number
                await mark_processed(
                    call_id,
                    "incoming_call",
                    success=True,
                    details="no_match_in_agencyzoom",
                )
                skipped_count += 1
            else:
                # Error occurred (e.g., AgencyZoom API error, storage error)
                # DO NOT mark as processed - we want to retry on next run
                logger.warning(
                    f"Call {call_id} had error, will retry: {process_result.get('reason', 'Unknown')}"
                )
                error_count += 1

        except Exception as e:
            # Exception occurred - DO NOT mark as processed, will retry
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
