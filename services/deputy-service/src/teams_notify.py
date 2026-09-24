"""
Post clock in/out and break events to the team's Teams group chat.

Replaces the Zapier zap's Teams step. Uses a Teams Workflows webhook ("Post to a chat
when a webhook request is received"), because Microsoft doesn't let an app post to a
group chat without signing in as a user. Disabled when TEAMS_WEBHOOK_URL is unset.
"""

import logging
from typing import Optional

import httpx

from .config import get_settings
from .timesheet_parser import TimesheetAction

logger = logging.getLogger(__name__)
settings = get_settings()

# Same wording and colors as the zap's posts ("Ilse ---> Break Started" in red)
LABELS = {
    TimesheetAction.CLOCK_IN: ("Clocked In", "Good"),
    TimesheetAction.CLOCK_OUT: ("Clocked Out", "Attention"),
    TimesheetAction.BREAK_START: ("Break Started", "Attention"),
    TimesheetAction.BREAK_END: ("Break Ended", "Good"),
}


def build_message(name: str, action: TimesheetAction) -> Optional[dict]:
    """Workflows webhook payload with one Adaptive Card, or None for actions we don't announce."""
    if action not in LABELS:
        return None
    label, color = LABELS[action]
    first_name = (name or "").split()[0] if (name or "").split() else "Someone"
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [{
            "type": "RichTextBlock",
            "inlines": [
                {"type": "TextRun", "text": f"{first_name} ---> "},
                {"type": "TextRun", "text": label, "color": color, "weight": "Bolder"},
            ],
        }],
    }
    return {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}],
    }


async def post_clock_event(name: str, action: TimesheetAction) -> bool:
    """Post to the Teams chat. Never raises: a Teams outage must not block the RingCentral update."""
    message = build_message(name, action)
    if not message or not settings.teams_webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(settings.teams_webhook_url, json=message)
        if response.status_code in (200, 202):
            logger.info(f"Posted to Teams: {name} {LABELS[action][0]}")
            return True
        logger.warning(f"Teams post failed for {name}: {response.status_code} - {response.text[:200]}")
    except Exception as e:
        logger.warning(f"Teams post failed for {name}: {e}")
    return False
