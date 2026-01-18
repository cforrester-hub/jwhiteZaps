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
    root_path="/api/ringcentral",
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
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check endpoint."""
    return HealthResponse(status="healthy", service="ringcentral-service")


@app.get("/test-connection", response_model=ConnectionTestResponse)
async def test_connection():
    """Test the connection to RingCentral API."""
    try:
        client = get_ringcentral_client()
        account_info = await client.test_connection()
        return ConnectionTestResponse(
            status="connected",
            account_id=account_info.get("id", "unknown"),
            account_name=account_info.get("mainNumber", "unknown"),
        )
    except Exception as e:
        logger.error(f"Connection test failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/calls", response_model=CallLogResponse)
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


@app.get("/calls/{call_id}", response_model=CallDetailResponse)
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


@app.get("/recordings/{recording_id}")
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


@app.get("/recordings/{recording_id}/insights", response_model=RingSenseResponse)
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
