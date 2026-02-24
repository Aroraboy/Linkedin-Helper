"""
tests/test_logger.py — Unit tests for the file logging module.

Tests cover:
    - Logger creation and configuration
    - Log file creation in logs/ directory
    - Log message formatting
    - Idempotent setup (no duplicate handlers)
"""

import logging
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

import config


class TestSetupLogging:
    """Tests for the setup_logging function."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, tmp_path):
        """Use a temporary directory for log files."""
        self.original_logs_dir = config.LOGS_DIR
        config.LOGS_DIR = tmp_path / "logs"

        # Clear any existing logger handlers
        logger = logging.getLogger("linkedin_tool")
        logger.handlers.clear()

        yield

        # Restore
        config.LOGS_DIR = self.original_logs_dir
        logger = logging.getLogger("linkedin_tool")
        logger.handlers.clear()

    def test_creates_logs_directory(self):
        from logger import setup_logging
        assert not config.LOGS_DIR.exists()
        setup_logging()
        assert config.LOGS_DIR.exists()

    def test_returns_logger(self):
        from logger import setup_logging
        logger = setup_logging()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "linkedin_tool"

    def test_log_file_created(self):
        from logger import setup_logging
        setup_logging()
        today = date.today().isoformat()
        log_file = config.LOGS_DIR / f"run_{today}.log"
        assert log_file.exists()

    def test_log_message_written(self):
        from logger import setup_logging
        logger = setup_logging()
        logger.info("Test message 12345")

        # Flush handlers
        for h in logger.handlers:
            h.flush()

        today = date.today().isoformat()
        log_file = config.LOGS_DIR / f"run_{today}.log"
        content = log_file.read_text(encoding="utf-8")
        assert "Test message 12345" in content

    def test_log_format(self):
        from logger import setup_logging
        logger = setup_logging()
        logger.info("Format check")

        for h in logger.handlers:
            h.flush()

        today = date.today().isoformat()
        log_file = config.LOGS_DIR / f"run_{today}.log"
        content = log_file.read_text(encoding="utf-8")

        # Should have timestamp | LEVEL | message format
        assert " | INFO     | " in content

    def test_no_duplicate_handlers(self):
        from logger import setup_logging

        logger1 = setup_logging()
        handler_count_1 = len(logger1.handlers)

        logger2 = setup_logging()
        handler_count_2 = len(logger2.handlers)

        assert handler_count_1 == handler_count_2
        assert logger1 is logger2

    def test_session_started_in_log(self):
        from logger import setup_logging
        setup_logging()

        today = date.today().isoformat()
        log_file = config.LOGS_DIR / f"run_{today}.log"
        content = log_file.read_text(encoding="utf-8")
        assert "Session started" in content

    def test_custom_log_level(self):
        from logger import setup_logging
        logger = setup_logging(level=logging.DEBUG)
        assert logger.level == logging.DEBUG
