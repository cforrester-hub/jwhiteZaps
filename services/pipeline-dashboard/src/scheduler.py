"""APScheduler setup for pipeline data sync."""

import logging
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the scheduler instance."""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


def start_scheduler():
    """Start the scheduler if not already running."""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("Scheduler started")


def shutdown_scheduler():
    """Shutdown the scheduler gracefully."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down")


def add_cron_job(func: Callable, cron_expression: str, job_id: str, name: Optional[str] = None):
    """Add a cron job to the scheduler."""
    sched = get_scheduler()

    parts = cron_expression.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {cron_expression}")

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )

    sched.add_job(
        func,
        trigger=trigger,
        id=job_id,
        name=name or job_id,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(f"Added cron job: {name or job_id} ({cron_expression})")
