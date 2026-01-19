"""
Transcription Service - Audio transcription and summarization using OpenAI.

This service provides endpoints to:
- Transcribe audio files using OpenAI Whisper
- Summarize transcripts using GPT
- Full pipeline: transcribe + summarize in one call
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .openai_client import (
    transcribe_and_summarize,
    transcribe_audio,
    summarize_transcript,
    download_audio,
)

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Transcription Service",
    description="Audio transcription and summarization using OpenAI Whisper and GPT",
    version="1.0.0",
    docs_url="/api/transcription/docs",
    redoc_url="/api/transcription/redoc",
    openapi_url="/api/transcription/openapi.json",
)


# =============================================================================
# MODELS
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    timestamp: str


class TranscribeRequest(BaseModel):
    """Request to transcribe audio from a URL."""
    audio_url: str
    filename: str = "audio.mp3"  # Hint for audio format


class TranscribeResponse(BaseModel):
    """Response from transcription."""
    transcript: str
    duration_hint: Optional[str] = None


class SummarizeRequest(BaseModel):
    """Request to summarize a transcript."""
    transcript: str
    context: Optional[str] = None  # e.g., "Inbound call from customer John Doe"


class SummarizeResponse(BaseModel):
    """Response from summarization."""
    summary: str
    action_items: list[str]


class TranscribeAndSummarizeRequest(BaseModel):
    """Request for full transcription + summarization pipeline."""
    audio_url: str
    filename: str = "audio.mp3"
    context: Optional[str] = None


class TranscribeAndSummarizeResponse(BaseModel):
    """Response from full pipeline."""
    transcript: str
    summary: str
    action_items: list[str]


# =============================================================================
# HEALTH ENDPOINTS
# =============================================================================


@app.get("/api/transcription/health", response_model=HealthResponse)
async def health_check():
    """Basic health check."""
    return HealthResponse(
        status="healthy",
        service="transcription-service",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/api/transcription/health/ready", response_model=HealthResponse)
async def readiness_check():
    """Readiness check - verifies OpenAI API key is configured."""
    if not settings.openai_api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")
    return HealthResponse(
        status="ready",
        service="transcription-service",
        timestamp=datetime.utcnow().isoformat(),
    )


# =============================================================================
# TRANSCRIPTION ENDPOINTS
# =============================================================================


@app.post("/api/transcription/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest):
    """
    Transcribe audio from a URL using OpenAI Whisper.

    - **audio_url**: URL to download the audio file from
    - **filename**: Filename hint for audio format (e.g., "call.mp3")
    """
    try:
        logger.info(f"Transcribing audio from URL")
        audio_data = await download_audio(request.audio_url)
        transcript = await transcribe_audio(audio_data, request.filename)
        return TranscribeResponse(transcript=transcript)
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcription/summarize", response_model=SummarizeResponse)
async def summarize(request: SummarizeRequest):
    """
    Summarize a transcript using GPT.

    - **transcript**: The text transcript to summarize
    - **context**: Optional context about the call (direction, caller, etc.)
    """
    try:
        logger.info("Summarizing transcript")
        result = await summarize_transcript(request.transcript, request.context)
        return SummarizeResponse(
            summary=result["summary"],
            action_items=result["action_items"],
        )
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/transcription/process", response_model=TranscribeAndSummarizeResponse)
async def transcribe_and_summarize_endpoint(request: TranscribeAndSummarizeRequest):
    """
    Full pipeline: transcribe audio and generate summary.

    This is the main endpoint for processing call recordings.

    - **audio_url**: URL to download the audio file from
    - **filename**: Filename hint for audio format
    - **context**: Optional context about the call
    """
    try:
        logger.info("Processing audio: transcribe + summarize")
        result = await transcribe_and_summarize(
            audio_url=request.audio_url,
            context=request.context,
            filename=request.filename,
        )
        return TranscribeAndSummarizeResponse(
            transcript=result["transcript"],
            summary=result["summary"],
            action_items=result["action_items"],
        )
    except Exception as e:
        logger.error(f"Process failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
