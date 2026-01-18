"""
Example workflow - demonstrates the workflow pattern.

This is a template you can copy when creating new workflows.
Delete this file once you have real workflows.
"""

import logging

from . import register_workflow, TriggerType, is_processed, mark_processed
from ..http_client import ringcentral

logger = logging.getLogger(__name__)


@register_workflow(
    name="example_call_sync",
    description="Example: Log recent calls (template workflow)",
    trigger_type=TriggerType.CRON,
    cron_expression="0 * * * *",  # Every hour at :00
    enabled=False,  # Disabled by default - this is just an example
)
async def run():
    """
    Example workflow that fetches recent calls and logs them.

    This demonstrates the typical workflow pattern:
    1. Fetch data from a service
    2. Check if items have been processed
    3. Process new items
    4. Mark items as processed

    Returns:
        dict with items_processed count
    """
    logger.info("Running example_call_sync workflow")

    # 1. Fetch data from RingCentral service
    try:
        response = await ringcentral.get_calls(per_page=10)
    except Exception as e:
        logger.error(f"Failed to fetch calls: {e}")
        raise

    calls = response.get("calls", [])
    items_processed = 0

    # 2. Process each call
    for call in calls:
        call_id = call.get("id")

        # Skip if already processed
        if await is_processed(call_id, "example_call_sync"):
            logger.debug(f"Skipping already processed call: {call_id}")
            continue

        # 3. Do something with the call
        # In a real workflow, you might:
        # - Send to AgencyZoom
        # - Post to Teams
        # - Upload recording to OneDrive
        logger.info(
            f"Processing call: {call_id} "
            f"({call.get('direction')}, {call.get('duration')}s, "
            f"from {call.get('from_number')} to {call.get('to_number')})"
        )

        # 4. Mark as processed
        await mark_processed(call_id, "example_call_sync", success=True)
        items_processed += 1

    logger.info(f"Processed {items_processed} new calls")
    return {"items_processed": items_processed}
