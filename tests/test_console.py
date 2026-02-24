"""
tests/test_console.py — Unit tests for the rich console UI module.

Tests cover:
    - Banner printing
    - Status messages (success, skip, error, info, cap)
    - Progress bar creation
    - Session summary table
    - Database summary table
    - Dashboard rendering
    - Export confirmation
    - Bar generation helper
"""

import io
import re
from unittest.mock import patch

import pytest
from rich.console import Console

from console import (
    _make_bar,
    create_progress,
    print_banner,
    print_cap,
    print_dashboard,
    print_db_summary,
    print_error,
    print_export_success,
    print_info,
    print_profile_header,
    print_session_summary,
    print_skip,
    print_success,
)

# Regex to strip ANSI escape sequences
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def capture_console_output(func, *args, **kwargs) -> str:
    """Capture rich console output by temporarily replacing the console."""
    import console as console_mod

    buf = io.StringIO()
    test_console = Console(file=buf, force_terminal=True, width=120)
    original = console_mod.console
    console_mod.console = test_console

    try:
        func(*args, **kwargs)
    finally:
        console_mod.console = original

    # Strip ANSI escape sequences for easier assertion
    raw = buf.getvalue()
    return _ANSI_RE.sub("", raw)


# ─── Banner Tests ────────────────────────────────────────────────────────────

class TestBanner:
    def test_banner_prints_title(self):
        output = capture_console_output(print_banner, "Test Title")
        assert "Test Title" in output

    def test_banner_dry_run(self):
        output = capture_console_output(print_banner, "Test Title", dry_run=True)
        assert "DRY RUN" in output

    def test_banner_no_dry_run_tag(self):
        output = capture_console_output(print_banner, "Test Title", dry_run=False)
        assert "DRY RUN" not in output


# ─── Status Message Tests ───────────────────────────────────────────────────

class TestStatusMessages:
    def test_print_success(self):
        output = capture_console_output(print_success, "Request sent")
        assert "✓" in output
        assert "Request sent" in output

    def test_print_skip(self):
        output = capture_console_output(print_skip, "Already pending")
        assert "○" in output
        assert "Already pending" in output

    def test_print_error(self):
        output = capture_console_output(print_error, "Something failed")
        assert "✗" in output
        assert "Something failed" in output

    def test_print_info(self):
        output = capture_console_output(print_info, "Processing 20 profiles")
        assert "ℹ" in output
        assert "Processing 20 profiles" in output

    def test_print_cap(self):
        output = capture_console_output(print_cap, "Daily cap reached")
        assert "Daily cap reached" in output

    def test_print_profile_header(self):
        output = capture_console_output(
            print_profile_header, 5, 100, "https://linkedin.com/in/john"
        )
        assert "5/100" in output
        assert "linkedin.com/in/john" in output

    def test_print_profile_header_with_name(self):
        output = capture_console_output(
            print_profile_header, 1, 10, "https://linkedin.com/in/john", name="John Doe"
        )
        assert "John Doe" in output


# ─── Progress Bar Tests ─────────────────────────────────────────────────────

class TestProgressBar:
    def test_create_progress_returns_progress(self):
        from rich.progress import Progress
        p = create_progress()
        assert isinstance(p, Progress)

    def test_progress_can_add_task(self):
        with create_progress() as p:
            task = p.add_task("Testing", total=10)
            p.update(task, advance=5)
            assert p.tasks[0].completed == 5


# ─── Summary Table Tests ────────────────────────────────────────────────────

class TestSessionSummary:
    def test_connect_summary(self):
        output = capture_console_output(
            print_session_summary,
            mode="connect",
            processed=10,
            sent=8,
            skipped=1,
            errors=1,
        )
        assert "Session Summary" in output
        assert "Processed" in output
        assert "10" in output
        assert "Requests Sent" in output
        assert "8" in output

    def test_message_summary(self):
        output = capture_console_output(
            print_session_summary,
            mode="message",
            processed=5,
            messaged=3,
            still_pending=1,
            skipped=1,
            errors=0,
        )
        assert "Messages Sent" in output
        assert "3" in output
        assert "Still Pending" in output

    def test_dry_run_summary(self):
        output = capture_console_output(
            print_session_summary,
            mode="connect",
            processed=5,
            sent=5,
            dry_run=True,
        )
        assert "DRY RUN" in output

    def test_both_mode_summary(self):
        output = capture_console_output(
            print_session_summary,
            mode="both",
            processed=10,
            sent=5,
            messaged=3,
            skipped=1,
            errors=1,
        )
        assert "Requests Sent" in output
        assert "Messages Sent" in output


class TestDbSummary:
    def test_db_summary_table(self):
        summary = {
            "pending": 900,
            "request_sent": 50,
            "connected": 30,
            "messaged": 10,
            "skipped": 5,
            "error": 5,
            "total": 1000,
        }
        output = capture_console_output(print_db_summary, summary)
        assert "900" in output
        assert "50" in output
        assert "1000" in output
        assert "pending" in output


# ─── Dashboard Tests ─────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_renders(self):
        summary = {
            "pending": 100,
            "request_sent": 20,
            "connected": 5,
            "messaged": 3,
            "skipped": 2,
            "error": 0,
            "total": 130,
        }
        daily_stats = [
            {"date": "2026-02-24", "connections_sent": 20, "messages_sent": 5},
            {"date": "2026-02-23", "connections_sent": 15, "messages_sent": 3},
        ]
        output = capture_console_output(
            print_dashboard, summary, 20, 5, daily_stats
        )
        assert "Status Dashboard" in output
        assert "Today's Usage" in output
        assert "Recent Activity" in output
        assert "2026-02-24" in output

    def test_dashboard_no_daily_stats(self):
        summary = {"pending": 0, "request_sent": 0, "connected": 0,
                    "messaged": 0, "skipped": 0, "error": 0, "total": 0}
        output = capture_console_output(print_dashboard, summary, 0, 0, [])
        assert "Status Dashboard" in output
        assert "Recent Activity" not in output


# ─── Export Confirmation ─────────────────────────────────────────────────────

class TestExportConfirmation:
    def test_export_success_message(self):
        output = capture_console_output(print_export_success, "results.csv", 500)
        assert "500" in output
        assert "results.csv" in output
        assert "✓" in output


# ─── Bar Helper Tests ───────────────────────────────────────────────────────

class TestMakeBar:
    def test_zero_pct(self):
        bar = _make_bar(0.0, "green")
        assert "0%" in bar

    def test_half_pct(self):
        bar = _make_bar(0.5, "yellow", width=10)
        assert "50%" in bar
        assert "█" in bar
        assert "░" in bar

    def test_full_pct(self):
        bar = _make_bar(1.0, "red", width=10)
        assert "100%" in bar
        # All filled
        assert "░" not in bar.replace("[red]", "").replace("[/red]", "").split(" ")[0]

    def test_custom_width(self):
        bar = _make_bar(0.5, "green", width=20)
        # Strip rich markup to count blocks
        raw = bar.replace("[green]", "").replace("[/green]", "")
        blocks = raw.split(" ")[0]
        assert len(blocks) == 20
