"""
console.py — Rich console UI for the LinkedIn Auto-Connect & Message Tool.

Provides color-coded output, progress bars, summary tables, and a status dashboard.
All console output goes through this module so the UI is consistent.
"""

import signal
import sys
from datetime import timedelta
from typing import Optional

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from config import DAILY_CONNECTION_CAP, DAILY_MESSAGE_CAP

# ─── Theme ────────────────────────────────────────────────────────────────────

THEME = Theme(
    {
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "info": "bold cyan",
        "muted": "dim",
        "header": "bold magenta",
        "cap": "bold yellow",
        "profile_name": "bold white",
    }
)

console = Console(theme=THEME)


# ─── Banners ─────────────────────────────────────────────────────────────────

def print_banner(title: str, dry_run: bool = False):
    """Print a styled banner for the start of a run."""
    suffix = " [warning]\\[DRY RUN][/warning]" if dry_run else ""
    console.print(
        Panel(
            f"[header]{title}[/header]{suffix}",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()


# ─── Status Messages ────────────────────────────────────────────────────────

def print_success(msg: str):
    """Print a green success message."""
    console.print(f"  [success]\u2713[/success] {escape(msg)}")


def print_skip(msg: str):
    """Print a yellow skip/warning message."""
    console.print(f"  [warning]\u25cb[/warning] {escape(msg)}")


def print_error(msg: str):
    """Print a red error message."""
    console.print(f"  [error]\u2717[/error] {escape(msg)}")


def print_info(msg: str):
    """Print a cyan informational message."""
    console.print(f"  [info]\u2139[/info] {escape(msg)}")


def print_cap(msg: str):
    """Print a yellow cap-reached message."""
    console.print(f"\n  [cap]\u26a0 {escape(msg)}[/cap]")


def print_profile_header(index: int, total: int, url: str, name: str = ""):
    """Print the header line for each profile being processed."""
    name_part = f"  [profile_name]{escape(name)}[/profile_name]" if name else ""
    console.print(
        f"\n  [muted]\\[{index}/{total}][/muted] {escape(url)}{name_part}"
    )


# ─── Progress Bar ────────────────────────────────────────────────────────────

def create_progress() -> Progress:
    """
    Create a rich Progress bar with ETA and counters.

    Usage:
        with create_progress() as progress:
            task = progress.add_task("Connecting...", total=100)
            progress.update(task, advance=1, description="Sending to John...")
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        transient=False,
    )


# ─── Summary Tables ─────────────────────────────────────────────────────────

def print_session_summary(
    mode: str,
    processed: int,
    sent: int = 0,
    messaged: int = 0,
    skipped: int = 0,
    still_pending: int = 0,
    errors: int = 0,
    dry_run: bool = False,
):
    """Print a rich table summarizing the session results."""
    title = f"Session Summary {'(DRY RUN)' if dry_run else ''}"

    table = Table(title=title, border_style="cyan", show_header=False, padding=(0, 2))
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    table.add_row("Processed", str(processed))

    if mode in ("connect", "both"):
        table.add_row("[green]Requests Sent[/green]", f"[green]{sent}[/green]")

    if mode in ("message", "both"):
        table.add_row("[green]Messages Sent[/green]", f"[green]{messaged}[/green]")
        table.add_row("Still Pending", str(still_pending))

    table.add_row("[yellow]Skipped[/yellow]", f"[yellow]{skipped}[/yellow]")
    table.add_row("[red]Errors[/red]", f"[red]{errors}[/red]")

    console.print()
    console.print(table)
    console.print()


def print_db_summary(summary: dict):
    """Print a rich table showing database status counts."""
    table = Table(border_style="dim", show_header=True, padding=(0, 2))
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")

    color_map = {
        "pending": "white",
        "request_sent": "cyan",
        "connected": "blue",
        "messaged": "green",
        "skipped": "yellow",
        "error": "red",
        "total": "bold white",
    }

    for status, count in summary.items():
        if status == "total":
            table.add_section()
        color = color_map.get(status, "white")
        table.add_row(f"[{color}]{status}[/{color}]", f"[{color}]{count}[/{color}]")

    console.print(table)


# ─── Status Dashboard ───────────────────────────────────────────────────────

def print_dashboard(
    summary: dict,
    daily_connections: int,
    daily_messages: int,
    daily_stats: list[dict],
):
    """
    Print the full status dashboard with profile counts, daily caps, and recent activity.
    """
    console.print(
        Panel(
            "[header]LinkedIn Auto-Connect — Status Dashboard[/header]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()

    # ── Profile Status Table ──
    print_db_summary(summary)
    console.print()

    # ── Daily Caps ──
    cap_table = Table(title="Today's Usage", border_style="dim", show_header=True, padding=(0, 2))
    cap_table.add_column("Counter", style="bold")
    cap_table.add_column("Used", justify="right")
    cap_table.add_column("Cap", justify="right", style="dim")
    cap_table.add_column("Bar", min_width=20)

    # Connection cap bar
    conn_pct = min(daily_connections / max(DAILY_CONNECTION_CAP, 1), 1.0)
    conn_color = "green" if conn_pct < 0.8 else "yellow" if conn_pct < 1.0 else "red"
    conn_bar = _make_bar(conn_pct, conn_color)

    cap_table.add_row(
        "Connections",
        str(daily_connections),
        str(DAILY_CONNECTION_CAP),
        conn_bar,
    )

    # Message cap bar
    msg_pct = min(daily_messages / max(DAILY_MESSAGE_CAP, 1), 1.0)
    msg_color = "green" if msg_pct < 0.8 else "yellow" if msg_pct < 1.0 else "red"
    msg_bar = _make_bar(msg_pct, msg_color)

    cap_table.add_row(
        "Messages",
        str(daily_messages),
        str(DAILY_MESSAGE_CAP),
        msg_bar,
    )

    console.print(cap_table)
    console.print()

    # ── Recent Activity ──
    if daily_stats:
        activity_table = Table(
            title="Recent Activity (last 7 days)",
            border_style="dim",
            show_header=True,
            padding=(0, 2),
        )
        activity_table.add_column("Date", style="bold")
        activity_table.add_column("Connections", justify="right")
        activity_table.add_column("Messages", justify="right")

        for day in daily_stats[:7]:
            activity_table.add_row(
                day["date"],
                str(day["connections_sent"]),
                str(day["messages_sent"]),
            )

        console.print(activity_table)
        console.print()


def _make_bar(pct: float, color: str, width: int = 20) -> str:
    """Create a simple text-based progress bar."""
    filled = int(pct * width)
    empty = width - filled
    return f"[{color}]{'█' * filled}{'░' * empty}[/{color}] {pct:.0%}"


# ─── Export Confirmation ─────────────────────────────────────────────────────

def print_export_success(path: str, count: int):
    """Print confirmation that CSV export succeeded."""
    console.print(f"\n  [success]✓[/success] Exported [bold]{count}[/bold] profiles to [bold]{escape(path)}[/bold]\n")
