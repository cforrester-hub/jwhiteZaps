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

    # Prompt provides context to help Whisper with domain-specific content
    prompt = (
        "Insurance agency phone call or voicemail. Caller may spell their name letter by letter. "
        "Common terms: policy number, claim, renewal, quote, coverage, deductible."
    )

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

    # Scale the summary to the call: a 35-minute quote call needs more than 2-3 sentences
    words = len(transcript.split())
    if words < 150:
        length = "1-2 sentences"
    elif words < 1500:
        length = "3-5 sentences"
    else:
        length = "a thorough paragraph (6-10 sentences) covering each topic discussed"

    system_prompt = f"""You summarize phone call transcripts for a Farmers Insurance agency.
The summary is saved as a note on the customer's record, so staff reading it later should understand
what happened without listening to the recording.

Provide:
1. A summary of the call in {length}, written as prose (no bullet points).
2. Action items or follow-ups that were committed to or requested, saying who will do each one
   (staff member or customer) when that is clear.

Include concrete specifics that were mentioned: people's names, policy types, properties or addresses,
vehicles, carriers, premiums or amounts, and dates (effective dates, deadlines, callbacks).
Do not invent details that are not in the transcript.

If the transcript is split into parts, the call was transferred between staff members. Summarize the
whole call and note who handled which part.

Format your response exactly as:
SUMMARY: [your summary here]

ACTION ITEMS:
- [action item 1]
- [action item 2]
(or "- None" if there are no action items)"""

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
        max_tokens=1000,
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
    segments: list[tuple[str, Optional[str]]],
    context: Optional[str] = None,
    filename: str = "audio.mp3",
) -> dict:
    """
    Full pipeline: download and transcribe every segment, then summarize them as one call.

    Args:
        segments: (audio_url, label) pairs in call order. Transferred calls have one
            recording per leg; the label is who handled that part (e.g. "Maria Prince").
        context: Optional context about the call
        filename: Filename hint for audio format

    Returns:
        dict with transcript, summary, and action_items
    """
    parts = []
    for i, (url, label) in enumerate(segments, 1):
        audio_data = await download_audio(url)
        logger.info(f"Downloaded segment {i}/{len(segments)}: {len(audio_data)} bytes")
        text = await transcribe_audio(audio_data, filename)
        if len(segments) > 1:
            header = f"--- Part {i} ({label}) ---" if label else f"--- Part {i} ---"
            text = f"{header}\n{text}"
        parts.append(text)
    transcript = "\n\n".join(parts)

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
