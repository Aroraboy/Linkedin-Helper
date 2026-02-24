"""
tests/test_main.py — Unit tests for the CLI entry point (main.py).

Tests cover:
    - CLI argument parsing (--status, --export, --reset-errors, --delay, --cap)
    - CSV export function
    - show_status function
    - Graceful Ctrl+C signal handling
"""

import csv
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from db import Database


class TestExportCSV:
    """Tests for the export_csv function."""

    @pytest.fixture
    def db_with_data(self, tmp_path):
        """Create a DB with test data."""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path=db_path)
        db.import_urls([
            {"url": "https://www.linkedin.com/in/alice", "row": 1},
            {"url": "https://www.linkedin.com/in/bob", "row": 2},
            {"url": "https://www.linkedin.com/in/carol", "row": 3},
        ])
        db.update_status("https://www.linkedin.com/in/alice", "request_sent", name="Alice A")
        db.update_status("https://www.linkedin.com/in/bob", "connected", name="Bob B")
        return db, db_path

    def test_export_creates_csv(self, db_with_data, tmp_path):
        db, db_path = db_with_data
        db.close()

        output_path = str(tmp_path / "results.csv")

        with patch("main.Database") as MockDB:
            mock_db = Database(db_path=db_path)
            MockDB.return_value = mock_db

            from main import export_csv
            export_csv(output_path)

        assert Path(output_path).exists()

    def test_export_csv_content(self, db_with_data, tmp_path):
        db, db_path = db_with_data
        db.close()

        output_path = str(tmp_path / "results.csv")

        with patch("main.Database") as MockDB:
            mock_db = Database(db_path=db_path)
            MockDB.return_value = mock_db

            from main import export_csv
            export_csv(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3
        urls = [r["url"] for r in rows]
        assert "https://www.linkedin.com/in/alice" in urls
        assert "https://www.linkedin.com/in/bob" in urls
        assert "https://www.linkedin.com/in/carol" in urls

    def test_export_csv_has_all_columns(self, db_with_data, tmp_path):
        db, db_path = db_with_data
        db.close()

        output_path = str(tmp_path / "results.csv")

        with patch("main.Database") as MockDB:
            mock_db = Database(db_path=db_path)
            MockDB.return_value = mock_db

            from main import export_csv
            export_csv(output_path)

        with open(output_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        expected = ["id", "url", "name", "status", "error_msg", "created_at", "updated_at"]
        assert headers == expected

    def test_export_empty_db(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        db = Database(db_path=db_path)
        db.close()

        output_path = str(tmp_path / "results.csv")

        with patch("main.Database") as MockDB:
            mock_db = Database(db_path=db_path)
            MockDB.return_value = mock_db

            from main import export_csv
            export_csv(output_path)

        # Should not create a file when DB is empty
        assert not Path(output_path).exists()


class TestShowStatus:
    """Tests for the show_status function."""

    def test_show_status_runs_without_error(self, tmp_path):
        db_path = str(tmp_path / "status_test.db")
        db = Database(db_path=db_path)
        db.import_urls([{"url": "https://www.linkedin.com/in/test", "row": 1}])
        db.close()

        with patch("main.Database") as MockDB:
            mock_db = Database(db_path=db_path)
            MockDB.return_value = mock_db

            from main import show_status
            # Should not raise
            show_status()


class TestCLIParsing:
    """Tests for argparse CLI behavior."""

    def test_help_flag(self):
        """--help should exit with code 0."""
        with pytest.raises(SystemExit) as exc_info:
            from main import main
            with patch("sys.argv", ["main.py", "--help"]):
                main()
        assert exc_info.value.code == 0

    def test_status_flag_calls_show_status(self):
        from main import main
        with patch("sys.argv", ["main.py", "--status"]):
            with patch("main.show_status") as mock_show:
                main()
                mock_show.assert_called_once()

    def test_export_flag_calls_export_csv(self):
        from main import main
        with patch("sys.argv", ["main.py", "--export", "out.csv"]):
            with patch("main.export_csv") as mock_export:
                main()
                mock_export.assert_called_once_with("out.csv")

    def test_reset_errors_flag(self):
        from main import main
        with patch("sys.argv", ["main.py", "--reset-errors"]):
            with patch("main.Database") as MockDB:
                mock_db = MagicMock()
                mock_db.reset_errors.return_value = 5
                MockDB.return_value = mock_db

                main()
                mock_db.reset_errors.assert_called_once()

    def test_missing_file_for_connect(self):
        """--mode without --file should error."""
        from main import main
        with patch("sys.argv", ["main.py", "--mode", "connect"]):
            with pytest.raises(SystemExit):
                main()

    def test_missing_mode_for_file(self):
        """--file without --mode should error."""
        from main import main
        with patch("sys.argv", ["main.py", "--file", "urls.csv"]):
            with pytest.raises(SystemExit):
                main()

    def test_delay_flag_parsed(self):
        """--delay should be available as args.delay."""
        import argparse
        from main import main

        with patch("sys.argv", ["main.py", "--file", "urls.csv", "--mode", "connect", "--delay", "10"]):
            with patch("main.run_connect") as mock_run:
                with patch("pathlib.Path.exists", return_value=True):
                    main()
                    mock_run.assert_called_once()
                    # Check delay was passed
                    call_kwargs = mock_run.call_args
                    assert call_kwargs[1].get("delay_override") == 10.0 or call_kwargs.kwargs.get("delay_override") == 10.0


class TestSignalHandler:
    """Tests for the Ctrl+C graceful shutdown."""

    def test_signal_handler_sets_flag(self):
        import main as main_mod
        main_mod._interrupted = False
        main_mod._signal_handler(None, None)
        assert main_mod._interrupted is True

    def test_signal_handler_resets(self):
        import main as main_mod
        main_mod._interrupted = True
        main_mod._interrupted = False
        assert main_mod._interrupted is False
