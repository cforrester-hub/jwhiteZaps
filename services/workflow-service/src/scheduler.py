"""APScheduler setup for cron-based workflows."""

import logging
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Global scheduler instance
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


def add_cron_job(
    func: Callable,
    cron_expression: str,
    job_id: str,
    name: Optional[str] = None,
):
    """
    Add a cron job to the scheduler.

    Args:
        func: The async function to run
        cron_expression: Cron expression (e.g., "*/15 * * * *" for every 15 minutes)
        job_id: Unique identifier for the job
        name: Human-readable name for logging
    """
    sched = get_scheduler()

    # Parse cron expression (minute hour day month day_of_week)
    parts = cron_expression.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    else:
        raise ValueError(f"Invalid cron expression: {cron_expression}")

    sched.add_job(
        func,
        trigger=trigger,
        id=job_id,
        name=name or job_id,
        replace_existing=True,
        max_instances=1,  # Prevent concurrent runs - critical to avoid duplicate notes
        coalesce=True,    # If multiple runs missed, only run once
    )
    logger.info(f"Added cron job: {name or job_id} ({cron_expression})")


def add_interval_job(
    func: Callable,
    minutes: int = 0,
    hours: int = 0,
    seconds: int = 0,
    job_id: str = None,
    name: Optional[str] = None,
):
    """
    Add an interval job to the scheduler.

    Args:
        func: The async function to run
        minutes: Run every N minutes
        hours: Run every N hours
        seconds: Run every N seconds
        job_id: Unique identifier for the job
        name: Human-readable name for logging
    """
    sched = get_scheduler()

    trigger = IntervalTrigger(hours=hours, minutes=minutes, seconds=seconds)

    sched.add_job(
        func,
        trigger=trigger,
        id=job_id,
        name=name or job_id,
        replace_existing=True,
        max_instances=1,  # Prevent concurrent runs
        coalesce=True,    # If multiple runs missed, only run once
    )
    logger.info(f"Added interval job: {name or job_id} (every {hours}h {minutes}m {seconds}s)")


def remove_job(job_id: str):
    """Remove a job from the scheduler."""
    sched = get_scheduler()
    sched.remove_job(job_id)
    logger.info(f"Removed job: {job_id}")


def list_jobs():
    """List all scheduled jobs."""
    sched = get_scheduler()
    return [
        {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        }
        for job in sched.get_jobs()
    ]
