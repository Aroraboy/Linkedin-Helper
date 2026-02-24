"""
logger.py — File logging setup for the LinkedIn Auto-Connect & Message Tool.

Creates timestamped log files in the logs/ directory:
    logs/run_2026-02-24.log

Each run appends to the day's log file so you have a full daily history.
"""

import logging
from datetime import date
from pathlib import Path

import config


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Set up file-based logging for the current session.

    Creates the logs/ directory if it doesn't exist, then configures a logger
    that writes to logs/run_YYYY-MM-DD.log (appending to the day's file).

    Args:
        level: Logging level (default: INFO).

    Returns:
        Configured logger instance.
    """
    logs_dir = config.LOGS_DIR

    # Ensure logs directory exists
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Log file named by date
    today = date.today().isoformat()
    log_file = logs_dir / f"run_{today}.log"

    # Create logger
    logger = logging.getLogger("linkedin_tool")
    logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    # File handler — append to daily log
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)

    # Format: timestamp | level | message
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info("=" * 60)
    logger.info("Session started")
    logger.info("=" * 60)

    return logger
