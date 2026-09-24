"""OpenAI client for transcription and summarization."""

import logging
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from openai import AsyncOpenAI

from .config import get_settings
from .scrub import scrub_sensitive

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
        # Card/bank/SSN numbers read aloud must not reach the summarizer or notes
        return scrub_sensitive(transcript)
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
        dict with 'summary', 'key_details', and 'action_items' keys
    """
    client = get_openai_client()
    transcript = scrub_sensitive(transcript)  # also covers /summarize callers with their own transcripts

    # Scale the summary to the call; the facts go in KEY DETAILS so the prose stays readable
    words = len(transcript.split())
    if words < 150:
        length = "1-2 sentences"
    elif words < 1500:
        length = "2-4 sentences"
    else:
        length = "4-7 sentences"

    system_prompt = f"""You summarize phone call transcripts for a Farmers Insurance agency.
The result is saved as a note on the customer's record, so a staff member reading it later should
understand what happened, and be able to act on it, without listening to the recording.

Write three sections:

SUMMARY: {length} of prose (no bullet points): why the person called, what was discussed or done,
and how the call ended. Name the staff member(s) and the customer when known. If the transcript is
split into parts, the call was transferred; say who handled which part.

KEY DETAILS: bullet points of the concrete facts someone would need to follow up, re-quote, or answer
a question later. One fact per bullet, most important first. Include whichever of these came up:
- Quotes: carrier, policy type, coverages and limits, deductibles, premium with its term (6-month or
  annual), fees, discounts applied or discussed, effective date
- Changes made or requested: vehicles or drivers added/removed, mileage, addresses, lienholders or
  mortgagees, named insureds
- Property details: address, year built, square footage, roof, rebuild/dwelling amount
- Vehicles: year, make, model, annual mileage
- Current or competing carrier, current premium, and why the customer is shopping
- Payment arrangements: method, autopay, amount paid or due (never the card or account number)
- Anything still missing or pending from the customer
Write "- None" if the call had no such details (common for short calls).

ACTION ITEMS: bullet points of follow-ups that were committed to or requested, each saying who will
do it (staff member or customer) and by when, if stated. Write "- None" if there are none.

Rules:
- Only include facts stated in the transcript. If a figure changed during the call, give the final one.
- Never include payment card numbers, security codes, bank account or routing numbers, or Social
  Security numbers, even if they appear in the transcript.

Format your response exactly as:
SUMMARY: ...

KEY DETAILS:
- ...

ACTION ITEMS:
- ..."""

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
        max_tokens=1500,
        temperature=0.3,  # Lower temperature for more consistent output
    )

    result_text = response.choices[0].message.content
    logger.info("Summarization complete")

    # Parse the response into its three sections
    summary = ""
    lists = {"key_details": [], "action_items": []}
    current_section = None

    for line in result_text.strip().split("\n"):
        line = line.strip().replace("**", "")
        upper = line.upper()
        if upper.startswith("SUMMARY:"):
            current_section = "summary"
            summary = line[8:].strip()
        elif upper.startswith("KEY DETAILS:"):
            current_section = "key_details"
        elif upper.startswith("ACTION ITEMS:"):
            current_section = "action_items"
        elif current_section == "summary" and line and not line.startswith("-"):
            summary += " " + line
        elif current_section in lists and line.startswith("-"):
            item = line[1:].strip()
            if item.lower().rstrip(".") not in ("none", "none mentioned"):
                lists[current_section].append(item)

    return {
        "summary": scrub_sensitive(summary.strip()),
        "key_details": [scrub_sensitive(i) for i in lists["key_details"]],
        "action_items": [scrub_sensitive(i) for i in lists["action_items"]],
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
            "key_details": [],
            "action_items": [],
        }

    # Summarize
    summary_result = await summarize_transcript(transcript, context)

    return {
        "transcript": transcript,
        "summary": summary_result["summary"],
        "key_details": summary_result["key_details"],
        "action_items": summary_result["action_items"],
    }
