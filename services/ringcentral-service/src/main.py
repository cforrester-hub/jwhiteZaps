"""
RingCentral Microservice - Call Log, Recordings, and AI Insights

This service provides endpoints to:
- Test RingCentral API connectivity
- Fetch call logs with detailed information
- Get call recordings
- Get RingSense AI insights (transcripts, summaries)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .config import get_settings
from .ringcentral_client import get_ringcentral_client

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RingCentral Service",
    description="Microservice for RingCentral call logs, recordings, and AI insights",
    version="1.0.0",
    docs_url="/api/ringcentral/docs",
    redoc_url="/api/ringcentral/redoc",
    openapi_url="/api/ringcentral/openapi.json",
)


# Response models
class HealthResponse(BaseModel):
    status: str
    service: str


class ConnectionTestResponse(BaseModel):
    status: str
    account_id: str
    account_name: str


class CallSummary(BaseModel):
    id: str
    session_id: str
    start_time: str
    duration: int
    direction: str
    from_number: str
    from_name: Optional[str] = None
    to_number: str
    to_name: Optional[str] = None
    result: str
    has_recording: bool
    recording_id: Optional[str] = None


class CallLogResponse(BaseModel):
    total_records: int
    page: int
    per_page: int
    calls: list[CallSummary]


class RecordingResponse(BaseModel):
    recording_id: str
    duration: int
    content_url: str
    content_type: str


class RingSenseResponse(BaseModel):
    available: bool
    transcript: Optional[list] = None
    summary: Optional[str] = None
    highlights: Optional[list] = None
    next_steps: Optional[list] = None
    error: Optional[str] = None


class CallDetailResponse(BaseModel):
    call: CallSummary
    recording: Optional[RecordingResponse] = None
    ai_insights: Optional[RingSenseResponse] = None


# Endpoints
@app.get("/api/ringcentral/health", response_model=HealthResponse)
async def health_check():
    """Basic health check endpoint."""
    return HealthResponse(status="healthy", service="ringcentral-service")


@app.get("/api/ringcentral/test-connection", response_model=ConnectionTestResponse)
async def test_connection():
    """Test the connection to RingCentral API."""
    try:
        client = get_ringcentral_client()
        account_info = await client.test_connection()
        return ConnectionTestResponse(
            status="connected",
            account_id=str(account_info.get("id", "unknown")),
            account_name=str(account_info.get("mainNumber", "unknown")),
        )
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/calls", response_model=CallLogResponse)
async def get_call_log(
    date_from: Optional[datetime] = Query(
        None, description="Start date (ISO format). Defaults to 7 days ago."
    ),
    date_to: Optional[datetime] = Query(
        None, description="End date (ISO format). Defaults to now."
    ),
    direction: Optional[str] = Query(
        None, description="Filter by direction: Inbound or Outbound"
    ),
    per_page: int = Query(50, ge=1, le=250, description="Records per page"),
    page: int = Query(1, ge=1, description="Page number"),
):
    """
    Fetch call log records.

    Returns a list of calls with basic information including whether
    recordings are available.
    """
    try:
        # Default to last 7 days if no dates provided
        if not date_from:
            date_from = datetime.now() - timedelta(days=7)
        if not date_to:
            date_to = datetime.now()

        client = get_ringcentral_client()
        result = await client.get_call_log(
            date_from=date_from,
            date_to=date_to,
            direction=direction,
            per_page=per_page,
            page=page,
        )

        calls = []
        for record in result.get("records", []):
            recording = record.get("recording")
            calls.append(
                CallSummary(
                    id=record.get("id", ""),
                    session_id=record.get("sessionId", ""),
                    start_time=record.get("startTime", ""),
                    duration=record.get("duration", 0),
                    direction=record.get("direction", ""),
                    from_number=record.get("from", {}).get("phoneNumber", ""),
                    from_name=record.get("from", {}).get("name"),
                    to_number=record.get("to", {}).get("phoneNumber", ""),
                    to_name=record.get("to", {}).get("name"),
                    result=record.get("result", ""),
                    has_recording=recording is not None,
                    recording_id=recording.get("id") if recording else None,
                )
            )

        paging = result.get("paging", {})
        return CallLogResponse(
            total_records=paging.get("totalRecords", len(calls)),
            page=paging.get("page", page),
            per_page=paging.get("perPage", per_page),
            calls=calls,
        )

    except Exception as e:
        logger.error(f"Failed to fetch call log: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/calls/{call_id}", response_model=CallDetailResponse)
async def get_call_details(
    call_id: str,
    include_recording: bool = Query(True, description="Include recording URL if available"),
    include_ai_insights: bool = Query(True, description="Include RingSense AI insights if available"),
):
    """
    Get detailed information about a specific call.

    Optionally includes recording download URL and AI insights.
    """
    try:
        client = get_ringcentral_client()

        # Get call details
        call_data = await client.get_call_with_details(call_id)

        recording_data = call_data.get("recording")
        call_summary = CallSummary(
            id=call_data.get("id", ""),
            session_id=call_data.get("sessionId", ""),
            start_time=call_data.get("startTime", ""),
            duration=call_data.get("duration", 0),
            direction=call_data.get("direction", ""),
            from_number=call_data.get("from", {}).get("phoneNumber", ""),
            from_name=call_data.get("from", {}).get("name"),
            to_number=call_data.get("to", {}).get("phoneNumber", ""),
            to_name=call_data.get("to", {}).get("name"),
            result=call_data.get("result", ""),
            has_recording=recording_data is not None,
            recording_id=recording_data.get("id") if recording_data else None,
        )

        response = CallDetailResponse(call=call_summary)

        # Get recording if available and requested
        if include_recording and recording_data:
            content_uri = recording_data.get("contentUri", "")
            if content_uri:
                download_url = await client.get_recording_content_url(content_uri)
                response.recording = RecordingResponse(
                    recording_id=recording_data.get("id", ""),
                    duration=recording_data.get("duration", 0),
                    content_url=download_url,
                    content_type=recording_data.get("contentType", "audio/mpeg"),
                )

        # Get AI insights if available and requested
        if include_ai_insights and recording_data:
            recording_id = recording_data.get("id")
            if recording_id:
                insights = await client.get_ringsense_insights(recording_id)

                if "error" in insights:
                    response.ai_insights = RingSenseResponse(
                        available=False,
                        error=insights.get("error"),
                    )
                else:
                    response.ai_insights = RingSenseResponse(
                        available=True,
                        transcript=insights.get("transcript"),
                        summary=insights.get("summary"),
                        highlights=insights.get("highlights"),
                        next_steps=insights.get("nextSteps"),
                    )

        return response

    except Exception as e:
        logger.error(f"Failed to get call details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/calls/{call_id}/raw")
async def get_call_raw(call_id: str):
    """
    Get raw call log data (for debugging).
    Shows the complete RingCentral API response including extension info.
    """
    try:
        client = get_ringcentral_client()
        return await client.get_call_with_details(call_id)
    except Exception as e:
        logger.error(f"Failed to get call details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/recordings/{recording_id}")
async def get_recording(recording_id: str):
    """
    Get recording metadata and download URL.
    """
    try:
        client = get_ringcentral_client()
        recording = await client.get_call_recording(recording_id)

        content_uri = recording.get("contentUri", "")
        download_url = await client.get_recording_content_url(content_uri) if content_uri else None

        return {
            "recording_id": recording.get("id"),
            "duration": recording.get("duration"),
            "content_url": download_url,
            "content_type": recording.get("contentType", "audio/mpeg"),
        }

    except Exception as e:
        logger.error(f"Failed to get recording: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/recordings/{recording_id}/insights", response_model=RingSenseResponse)
async def get_recording_insights(recording_id: str):
    """
    Get RingSense AI insights for a specific recording.

    Returns transcript, summary, highlights, and next steps if available.
    """
    try:
        client = get_ringcentral_client()
        insights = await client.get_ringsense_insights(recording_id)

        if "error" in insights:
            return RingSenseResponse(
                available=False,
                error=insights.get("error"),
            )

        return RingSenseResponse(
            available=True,
            transcript=insights.get("transcript"),
            summary=insights.get("summary"),
            highlights=insights.get("highlights"),
            next_steps=insights.get("nextSteps"),
        )

    except Exception as e:
        logger.error(f"Failed to get insights: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# VOICEMAIL ENDPOINTS (Message Store)
# =============================================================================


class VoicemailAttachment(BaseModel):
    id: str
    uri: str
    content_type: str
    duration: Optional[int] = None


class VoicemailMessage(BaseModel):
    id: str
    from_number: str
    from_name: Optional[str] = None
    to_number: str
    creation_time: str
    read_status: str
    attachments: list[VoicemailAttachment]
    vm_transcription_status: Optional[str] = None
    subject: Optional[str] = None


class VoicemailListResponse(BaseModel):
    total_records: int
    page: int
    per_page: int
    messages: list[VoicemailMessage]


class VoicemailDetailResponse(BaseModel):
    message: VoicemailMessage
    content_url: Optional[str] = None


@app.get("/api/ringcentral/voicemails", response_model=VoicemailListResponse)
async def get_voicemails(
    date_from: Optional[datetime] = Query(None, description="Start date (ISO format)"),
    date_to: Optional[datetime] = Query(None, description="End date (ISO format)"),
    per_page: int = Query(50, ge=1, le=250, description="Records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    all_extensions: bool = Query(False, description="Search across all extensions (slower but comprehensive)"),
):
    """
    Fetch voicemail messages from the message store.

    Returns voicemails with their attachments (audio recordings).
    Note: By default only searches the authenticated user's extension.
    Use all_extensions=true to search across ALL extensions in the account.
    """
    try:
        client = get_ringcentral_client()

        if all_extensions:
            # Search across all extensions
            records = await client.get_all_voicemail_messages(
                date_from=date_from,
                date_to=date_to,
                per_page=per_page,
            )
        else:
            # Search only current extension
            result = await client.get_voicemail_messages(
                date_from=date_from,
                date_to=date_to,
                per_page=per_page,
                page=page,
            )
            records = result.get("records", [])

        messages = []
        for record in records:
            attachments = []
            for att in record.get("attachments", []):
                attachments.append(
                    VoicemailAttachment(
                        id=str(att.get("id", "")),
                        uri=att.get("uri", ""),
                        content_type=att.get("contentType", "audio/mpeg"),
                        duration=att.get("vmDuration"),
                    )
                )

            messages.append(
                VoicemailMessage(
                    id=str(record.get("id", "")),
                    from_number=record.get("from", {}).get("phoneNumber", ""),
                    from_name=record.get("from", {}).get("name"),
                    to_number=record.get("to", [{}])[0].get("phoneNumber", "") if record.get("to") else "",
                    creation_time=record.get("creationTime", ""),
                    read_status=record.get("readStatus", ""),
                    attachments=attachments,
                    vm_transcription_status=record.get("vmTranscriptionStatus"),
                    subject=record.get("subject"),
                )
            )

        return VoicemailListResponse(
            total_records=len(messages),
            page=page if not all_extensions else 1,
            per_page=per_page,
            messages=messages,
        )

    except Exception as e:
        logger.error(f"Failed to fetch voicemails: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/voicemails/{message_id}", response_model=VoicemailDetailResponse)
async def get_voicemail(message_id: str, include_content_url: bool = True):
    """
    Get a specific voicemail message with optional download URL.
    """
    try:
        client = get_ringcentral_client()
        record = await client.get_voicemail_message(message_id)

        attachments = []
        content_url = None
        for att in record.get("attachments", []):
            attachments.append(
                VoicemailAttachment(
                    id=str(att.get("id", "")),
                    uri=att.get("uri", ""),
                    content_type=att.get("contentType", "audio/mpeg"),
                    duration=att.get("vmDuration"),
                )
            )
            # Get download URL for first audio attachment
            if include_content_url and not content_url and att.get("uri"):
                content_url = await client.get_voicemail_content_url(att.get("uri"))

        message = VoicemailMessage(
            id=str(record.get("id", "")),
            from_number=record.get("from", {}).get("phoneNumber", ""),
            from_name=record.get("from", {}).get("name"),
            to_number=record.get("to", [{}])[0].get("phoneNumber", "") if record.get("to") else "",
            creation_time=record.get("creationTime", ""),
            read_status=record.get("readStatus", ""),
            attachments=attachments,
            vm_transcription_status=record.get("vmTranscriptionStatus"),
            subject=record.get("subject"),
        )

        return VoicemailDetailResponse(
            message=message,
            content_url=content_url,
        )

    except Exception as e:
        logger.error(f"Failed to get voicemail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/ringcentral/voicemails/find-for-call/{call_id}")
async def find_voicemail_for_call(
    call_id: str,
    from_number: str = Query(..., description="Caller's phone number"),
    start_time: str = Query(..., description="Call start time (ISO format)"),
):
    """
    Find the voicemail message associated with a call.

    Since voicemails in message-store don't link directly to call-log entries,
    this matches by phone number and approximate time.
    """
    try:
        client = get_ringcentral_client()
        message = await client.find_voicemail_for_call(call_id, from_number, start_time)

        if not message:
            raise HTTPException(status_code=404, detail="Voicemail not found for this call")

        # Get content URL for the first attachment
        content_url = None
        attachments = message.get("attachments", [])
        if attachments and attachments[0].get("uri"):
            content_url = await client.get_voicemail_content_url(attachments[0].get("uri"))

        return {
            "message_id": str(message.get("id", "")),
            "from_number": message.get("from", {}).get("phoneNumber", ""),
            "from_name": message.get("from", {}).get("name"),
            "creation_time": message.get("creationTime", ""),
            "content_url": content_url,
            "content_type": attachments[0].get("contentType", "audio/mpeg") if attachments else None,
            "duration": attachments[0].get("vmDuration") if attachments else None,
            "vm_transcription_status": message.get("vmTranscriptionStatus"),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find voicemail for call: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PRESENCE / DND (Do Not Disturb) ENDPOINTS
# =============================================================================


class PresenceResponse(BaseModel):
    extension_id: str
    dnd_status: str
    user_status: str
    presence_status: Optional[str] = None


class UpdateDndRequest(BaseModel):
    dnd_status: str  # TakeAllCalls, DoNotAcceptDepartmentCalls, etc.
    user_status: str = "Available"


@app.get("/api/ringcentral/extensions/{extension_id}/presence", response_model=PresenceResponse)
async def get_extension_presence(extension_id: str):
    """
    Get the presence/DND status of an extension.
    """
    try:
        client = get_ringcentral_client()
        presence = await client.get_extension_presence(extension_id)

        return PresenceResponse(
            extension_id=str(presence.get("extension", {}).get("id", extension_id)),
            dnd_status=presence.get("dndStatus", "Unknown"),
            user_status=presence.get("userStatus", "Unknown"),
            presence_status=presence.get("presenceStatus"),
        )
    except Exception as e:
        logger.error(f"Failed to get presence for extension {extension_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/ringcentral/extensions/{extension_id}/presence", response_model=PresenceResponse)
async def update_extension_presence(extension_id: str, request: UpdateDndRequest):
    """
    Update the DND status of an extension.

    dnd_status options:
    - TakeAllCalls: Accept all calls including queue calls
    - DoNotAcceptDepartmentCalls: Accept direct calls only, no queue calls
    - TakeDepartmentCallsOnly: Accept queue calls only
    - DoNotAcceptAnyCalls: Reject all calls
    """
    try:
        client = get_ringcentral_client()
        presence = await client.update_extension_dnd(
            extension_id=extension_id,
            dnd_status=request.dnd_status,
            user_status=request.user_status,
        )

        return PresenceResponse(
            extension_id=str(presence.get("extension", {}).get("id", extension_id)),
            dnd_status=presence.get("dndStatus", "Unknown"),
            user_status=presence.get("userStatus", "Unknown"),
            presence_status=presence.get("presenceStatus"),
        )
    except Exception as e:
        logger.error(f"Failed to update presence for extension {extension_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ringcentral/extensions/{extension_id}/available", response_model=PresenceResponse)
async def set_extension_available(extension_id: str):
    """
    Set an extension to accept all calls (clocked in / off break).
    """
    try:
        client = get_ringcentral_client()
        presence = await client.set_extension_available(extension_id)

        return PresenceResponse(
            extension_id=str(presence.get("extension", {}).get("id", extension_id)),
            dnd_status=presence.get("dndStatus", "Unknown"),
            user_status=presence.get("userStatus", "Unknown"),
            presence_status=presence.get("presenceStatus"),
        )
    except Exception as e:
        logger.error(f"Failed to set extension {extension_id} available: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ringcentral/extensions/{extension_id}/unavailable", response_model=PresenceResponse)
async def set_extension_unavailable(extension_id: str):
    """
    Set an extension to not accept department/queue calls (clocked out / on break).
    """
    try:
        client = get_ringcentral_client()
        presence = await client.set_extension_unavailable(extension_id)

        return PresenceResponse(
            extension_id=str(presence.get("extension", {}).get("id", extension_id)),
            dnd_status=presence.get("dndStatus", "Unknown"),
            user_status=presence.get("userStatus", "Unknown"),
            presence_status=presence.get("presenceStatus"),
        )
    except Exception as e:
        logger.error(f"Failed to set extension {extension_id} unavailable: {e}")
        raise HTTPException(status_code=500, detail=str(e))
