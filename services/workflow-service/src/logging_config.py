"""Structured JSON logging configuration for workflow service."""

import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from pythonjsonlogger import jsonlogger

from .config import get_settings


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)

        # Add timestamp in ISO format
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Add service name
        log_record["service"] = "workflow-service"

        # Add log level
        log_record["level"] = record.levelname

        # Add logger name
        log_record["logger"] = record.name

        # Add source location
        log_record["source"] = f"{record.filename}:{record.lineno}"

        # Remove redundant fields
        if "levelname" in log_record:
            del log_record["levelname"]
        if "name" in log_record:
            del log_record["name"]


def setup_logging(log_level: Optional[str] = None) -> None:
    """
    Configure structured JSON logging for the application.

    Args:
        log_level: Override log level (defaults to settings.log_level)
    """
    settings = get_settings()
    level = getattr(logging, (log_level or settings.log_level).upper())

    # Create JSON formatter
    formatter = CustomJsonFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s",
        rename_fields={"levelname": "level", "name": "logger"},
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add stdout handler with JSON formatter
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(level)
    root_logger.addHandler(stdout_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)
