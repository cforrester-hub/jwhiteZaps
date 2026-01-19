"""OpenAI client for transcription and summarization."""

import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from openai import AsyncOpenAI

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize OpenAI client
_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create the OpenAI client."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def download_audio(url: str) -> bytes:
    """Download audio from a URL."""
    logger.info(f"Downloading audio from URL...")
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def transcribe_audio(audio_data: bytes, filename: str = "audio.mp3") -> str:
    """
    Transcribe audio using OpenAI's transcription API.

    Args:
        audio_data: Raw audio bytes
        filename: Filename hint for the audio format

    Returns:
        Transcribed text
    """
    client = get_openai_client()

    # Write audio to a temporary file (OpenAI API requires file-like object)
    suffix = Path(filename).suffix or ".mp3"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(audio_data)
        tmp_path = tmp_file.name

    # Build a prompt to help with transcription accuracy
    # This helps the model understand context and handle spelled-out names
    prompt = """This is a voicemail or phone call for an insurance agency.
The caller may spell out their name letter by letter (e.g., "R-O-B-A-S-C-I-O-T-T-I").
When letters are spelled out, transcribe them as individual letters with hyphens.
Common topics include: policy numbers, insurance claims, renewals, quotes, and coverage questions.
Names mentioned may be unusual - transcribe them phonetically if unclear."""

    try:
        logger.info(f"Transcribing audio with {settings.whisper_model}...")
        with open(tmp_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=settings.whisper_model,
                file=audio_file,
                response_format="text",
                prompt=prompt,
            )
        logger.info(f"Transcription complete: {len(transcript)} characters")
        return transcript
    finally:
        # Clean up temp file
        Path(tmp_path).unlink(missing_ok=True)


async def summarize_transcript(
    transcript: str,
    context: Optional[str] = None,
) -> dict:
    """
    Summarize a call transcript using GPT.

    Args:
        transcript: The transcribed text
        context: Optional context about the call (direction, caller info, etc.)

    Returns:
        dict with 'summary' and 'action_items' keys
    """
    client = get_openai_client()

    system_prompt = """You are an assistant that summarizes phone call transcripts for an insurance agency.
Your job is to extract the key information from the call and present it concisely.

Provide:
1. A brief summary (2-3 sentences) of what the call was about
2. Any action items or follow-ups mentioned (if any)

Format your response as:
SUMMARY: [your summary here]

ACTION ITEMS:
- [action item 1]
- [action item 2]
(or "None mentioned" if no action items)

Keep it professional and concise. Focus on insurance-related topics like policy questions, claims, quotes, renewals, etc."""

    user_prompt = f"""Please summarize this phone call transcript:

{f"Context: {context}" if context else ""}

TRANSCRIPT:
{transcript}"""

    logger.info(f"Summarizing transcript with {settings.summary_model}...")
    response = await client.chat.completions.create(
        model=settings.summary_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=500,
        temperature=0.3,  # Lower temperature for more consistent output
    )

    result_text = response.choices[0].message.content
    logger.info("Summarization complete")

    # Parse the response into summary and action items
    summary = ""
    action_items = []

    lines = result_text.strip().split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if line.upper().startswith("SUMMARY:"):
            current_section = "summary"
            summary = line[8:].strip()
        elif line.upper().startswith("ACTION ITEMS:"):
            current_section = "action_items"
        elif current_section == "summary" and line and not line.startswith("-"):
            summary += " " + line
        elif current_section == "action_items" and line.startswith("-"):
            item = line[1:].strip()
            if item.lower() != "none mentioned" and item.lower() != "none":
                action_items.append(item)

    return {
        "summary": summary.strip(),
        "action_items": action_items,
        "raw_response": result_text,
    }


async def transcribe_and_summarize(
    audio_url: str,
    context: Optional[str] = None,
    filename: str = "audio.mp3",
) -> dict:
    """
    Full pipeline: download audio, transcribe, and summarize.

    Args:
        audio_url: URL to download the audio from
        context: Optional context about the call
        filename: Filename hint for audio format

    Returns:
        dict with transcript, summary, and action_items
    """
    # Download the audio
    audio_data = await download_audio(audio_url)
    logger.info(f"Downloaded {len(audio_data)} bytes of audio")

    # Transcribe
    transcript = await transcribe_audio(audio_data, filename)

    # Skip summarization if transcript is too short
    if len(transcript.strip()) < 50:
        logger.info("Transcript too short for meaningful summary")
        return {
            "transcript": transcript,
            "summary": "Call too short for summary.",
            "action_items": [],
        }

    # Summarize
    summary_result = await summarize_transcript(transcript, context)

    return {
        "transcript": transcript,
        "summary": summary_result["summary"],
        "action_items": summary_result["action_items"],
    }
