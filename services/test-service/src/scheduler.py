"""
Scheduler for cron-like background jobs.
Uses APScheduler for flexible scheduling.
"""

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()


async def example_cron_job():
    """
    Example cron job that runs on a schedule.
    Replace this with actual business logic for your microservices.
    """
    logger.info(f"Cron job executed at {datetime.utcnow().isoformat()}")


def setup_scheduler():
    """
    Configure and start the scheduler.
    Add your cron jobs here.
    """
    # Example: Run every minute
    # For testing purposes - in production you'd use more realistic schedules
    scheduler.add_job(
        example_cron_job,
        CronTrigger(minute="*"),  # Every minute
        id="example_cron_job",
        name="Example Cron Job",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")


def shutdown_scheduler():
    """Gracefully shutdown the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
