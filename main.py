"""
main.py — CLI entry point for the LinkedIn Auto-Connect & Message Tool.

Usage:
    python main.py --file urls.xlsx --mode connect           Send connection requests
    python main.py --file urls.xlsx --mode message           Send follow-up messages
    python main.py --file urls.xlsx --mode both              Connect then message
    python main.py --file urls.csv --mode connect --dry-run  Simulate without clicking
    python main.py --status                                  Show progress dashboard
    python main.py --reset-errors                            Retry failed profiles
    python main.py --export results.csv                      Export all profiles to CSV
"""

import argparse
import csv
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from config import (
    DAILY_CONNECTION_CAP,
    DAILY_MESSAGE_CAP,
    DELAY_BETWEEN_PROFILES,
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_MESSAGED,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_SKIPPED,
    get_connection_note_template,
    get_followup_message_template,
)
from console import (
    console,
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
from db import COUNTER_CONNECTIONS, COUNTER_MESSAGES, Database
from linkedin_bot import LinkedInBot, LinkedInCapReachedError, SessionExpiredError
from logger import setup_logging
from spreadsheet_reader import read_spreadsheet

# ─── Global state for graceful shutdown ──────────────────────────────────────

_interrupted = False
_bot_ref: LinkedInBot | None = None
_db_ref: Database | None = None


def _signal_handler(sig, frame):
    """Handle Ctrl+C gracefully — set flag so the main loop exits cleanly."""
    global _interrupted
    _interrupted = True
    console.print("\n\n  [warning]⚠ Ctrl+C detected — finishing current profile then stopping...[/warning]")


signal.signal(signal.SIGINT, _signal_handler)


# ─── Connect Workflow ────────────────────────────────────────────────────────

def run_connect(
    file_path: str,
    dry_run: bool = False,
    cap: int = 0,
    delay_override: float = 0,
):
    """
    Run the connection request workflow.

    Reads URLs from spreadsheet, imports to DB, then processes pending profiles
    one by one — visiting each and sending a personalized connection request.

    Args:
        file_path: Path to CSV/XLSX/Google Sheets URL with LinkedIn profile URLs.
        dry_run: If True, visit profiles but don't click any buttons.
        cap: Override daily connection cap. 0 = use default from config.
        delay_override: Override minimum delay between profiles. 0 = use default.
    """
    global _interrupted, _bot_ref, _db_ref
    _interrupted = False

    logger = setup_logging()
    daily_cap = cap if cap > 0 else DAILY_CONNECTION_CAP

    print_banner("LinkedIn Auto-Connect Tool", dry_run=dry_run)
    logger.info(f"Connect mode started | file={file_path} | dry_run={dry_run} | cap={daily_cap}")

    # Step 1: Read spreadsheet and import URLs
    urls = read_spreadsheet(file_path)
    if not urls:
        print_error("No valid LinkedIn URLs found in the file.")
        logger.error("No valid LinkedIn URLs found.")
        return

    db = Database()
    _db_ref = db
    import_result = db.import_urls(urls)
    print_info(
        f"Imported {import_result['imported']} new URLs, "
        f"skipped {import_result['skipped']} duplicates."
    )
    logger.info(f"Imported {import_result['imported']}, skipped {import_result['skipped']}")

    # Step 2: Check daily cap
    if db.is_daily_cap_reached(COUNTER_CONNECTIONS):
        today_count = db.get_daily_count(COUNTER_CONNECTIONS)
        print_cap(f"Daily connection cap reached ({today_count}/{daily_cap}). Try again tomorrow.")
        logger.warning(f"Daily cap reached: {today_count}/{daily_cap}")
        db.close()
        return

    # Step 3: Get pending profiles
    remaining_today = daily_cap - db.get_daily_count(COUNTER_CONNECTIONS)
    pending = db.get_pending_profiles(limit=remaining_today)

    if not pending:
        print_info("No pending profiles to process.")
        summary = db.get_summary()
        print_db_summary(summary)
        db.close()
        return

    print_info(
        f"Processing {len(pending)} profiles "
        f"(daily cap: {daily_cap}, remaining: {remaining_today})"
    )

    # Step 4: Load template
    try:
        note_template = get_connection_note_template()
    except FileNotFoundError as e:
        print_error(str(e))
        db.close()
        return

    # Step 5: Launch browser and start processing
    bot = LinkedInBot()
    _bot_ref = bot

    # Stats for this session
    processed = 0
    sent = 0
    skipped = 0
    errors = 0

    try:
        logged_in = bot.start()

        if not logged_in:
            bot.login()
            if not bot.is_logged_in():
                print_error("Login failed. Please try again.")
                bot.close()
                db.close()
                return

        logger.info(f"Browser launched, logged in. Processing {len(pending)} profiles.")

        with create_progress() as progress:
            task = progress.add_task("Connecting...", total=len(pending))

            for i, profile in enumerate(pending):
                if _interrupted:
                    logger.info("Interrupted by user (Ctrl+C)")
                    break

                url = profile["url"]

                # Check daily cap before each profile
                if db.is_daily_cap_reached(COUNTER_CONNECTIONS):
                    print_cap(f"Daily connection cap reached ({daily_cap}). Stopping.")
                    logger.warning("Daily cap reached mid-run")
                    break

                # Update progress bar description
                progress.update(task, description=f"[{i+1}/{len(pending)}] {url[-40:]}...")

                try:
                    if dry_run:
                        status = bot.dry_run_connection(url, note_template)
                    else:
                        status = bot.send_connection_request(url, note_template)

                    # Extract name for logging
                    name_info = None
                    try:
                        name_el = bot.page.query_selector("h1")
                        if name_el:
                            name_info = name_el.inner_text().strip()
                    except Exception:
                        pass

                    if status == STATUS_REQUEST_SENT:
                        if not dry_run:
                            db.update_status(url, STATUS_REQUEST_SENT, name=name_info)
                            db.increment_daily_counter(COUNTER_CONNECTIONS)
                        sent += 1
                        logger.info(f"REQUEST_SENT | {url} | {name_info or 'N/A'}")

                    elif status == "already_connected":
                        if not dry_run:
                            db.update_status(url, STATUS_CONNECTED, name=name_info)
                        skipped += 1
                        logger.info(f"ALREADY_CONNECTED | {url}")

                    elif status == "already_pending":
                        if not dry_run:
                            db.update_status(url, STATUS_REQUEST_SENT)
                        skipped += 1
                        logger.info(f"ALREADY_PENDING | {url}")

                    elif status == STATUS_SKIPPED:
                        if not dry_run:
                            db.update_status(url, STATUS_SKIPPED)
                        skipped += 1
                        logger.info(f"SKIPPED | {url}")

                    elif status == "cap_reached":
                        logger.warning(f"LINKEDIN_CAP_REACHED | {url}")
                        if not dry_run:
                            db.update_status(url, STATUS_PENDING)
                        break

                    else:
                        if not dry_run:
                            db.update_status(url, STATUS_ERROR, error_msg=f"Status: {status}")
                        errors += 1
                        logger.error(f"ERROR | {url} | Status: {status}")

                    processed += 1

                except Exception as e:
                    if not dry_run:
                        db.update_status(url, STATUS_ERROR, error_msg=str(e)[:200])
                    errors += 1
                    processed += 1
                    logger.error(f"EXCEPTION | {url} | {e}")

                # Advance progress bar
                progress.update(task, advance=1)

                # Delay between profiles
                if i < len(pending) - 1 and not _interrupted:
                    if bot.should_take_long_pause(processed):
                        if not dry_run:
                            bot.long_pause()
                    else:
                        if not dry_run:
                            if delay_override > 0:
                                time.sleep(delay_override)
                            else:
                                bot.profile_delay()

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print_error(f"Unexpected error: {e}")

    finally:
        bot.close()
        _bot_ref = None

    # Print session summary
    print_session_summary(
        mode="connect",
        processed=processed,
        sent=sent,
        skipped=skipped,
        errors=errors,
        dry_run=dry_run,
    )
    logger.info(f"Connect session done | processed={processed} sent={sent} skipped={skipped} errors={errors}")

    if not dry_run:
        summary = db.get_summary()
        print_db_summary(summary)

    db.close()
    _db_ref = None


# ─── Message Workflow ────────────────────────────────────────────────────────

def run_message(
    file_path: str,
    dry_run: bool = False,
    cap: int = 0,
    delay_override: float = 0,
):
    """
    Run the follow-up message workflow.

    Reads URLs from spreadsheet, imports to DB, then checks profiles with
    status 'request_sent' to see if they've accepted. If connected, sends
    a personalized follow-up message.

    Args:
        file_path: Path to CSV/XLSX/Google Sheets URL with LinkedIn profile URLs.
        dry_run: If True, visit profiles but don't send any messages.
        cap: Override daily message cap. 0 = use default from config.
        delay_override: Override minimum delay between profiles. 0 = use default.
    """
    global _interrupted, _bot_ref, _db_ref
    _interrupted = False

    logger = setup_logging()
    daily_cap = cap if cap > 0 else DAILY_MESSAGE_CAP

    print_banner("LinkedIn Follow-Up Messaging", dry_run=dry_run)
    logger.info(f"Message mode started | file={file_path} | dry_run={dry_run} | cap={daily_cap}")

    # Step 1: Import URLs
    urls = read_spreadsheet(file_path)
    if not urls:
        print_error("No valid LinkedIn URLs found in the file.")
        logger.error("No valid LinkedIn URLs found.")
        return

    db = Database()
    _db_ref = db
    import_result = db.import_urls(urls)
    if import_result["imported"] > 0:
        print_info(f"Imported {import_result['imported']} new URLs.")

    # Step 2: Check daily message cap
    if db.is_daily_cap_reached(COUNTER_MESSAGES):
        today_count = db.get_daily_count(COUNTER_MESSAGES)
        print_cap(f"Daily message cap reached ({today_count}/{daily_cap}). Try again tomorrow.")
        logger.warning(f"Daily message cap reached: {today_count}/{daily_cap}")
        db.close()
        return

    # Step 3: Get candidates
    remaining_today = daily_cap - db.get_daily_count(COUNTER_MESSAGES)
    candidates = db.get_accepted_profiles(limit=remaining_today)

    if not candidates:
        print_info("No profiles with 'request_sent' status to check for messaging.")
        print_info("Run connect mode first, then wait for connections to be accepted.")
        summary = db.get_summary()
        print_db_summary(summary)
        db.close()
        return

    print_info(
        f"Checking {len(candidates)} profiles for accepted connections "
        f"(daily message cap: {daily_cap}, remaining: {remaining_today})"
    )

    # Step 4: Load template
    try:
        message_template = get_followup_message_template()
    except FileNotFoundError as e:
        print_error(str(e))
        db.close()
        return

    # Step 5: Launch browser and start processing
    bot = LinkedInBot()
    _bot_ref = bot

    # Stats
    processed = 0
    messaged = 0
    still_pending = 0
    skipped = 0
    errors = 0

    try:
        logged_in = bot.start()

        if not logged_in:
            bot.login()
            if not bot.is_logged_in():
                print_error("Login failed. Please try again.")
                bot.close()
                db.close()
                return

        logger.info(f"Browser launched, logged in. Checking {len(candidates)} profiles.")

        with create_progress() as progress:
            task = progress.add_task("Messaging...", total=len(candidates))

            for i, profile in enumerate(candidates):
                if _interrupted:
                    logger.info("Interrupted by user (Ctrl+C)")
                    break

                url = profile["url"]

                # Check daily cap before each profile
                if db.is_daily_cap_reached(COUNTER_MESSAGES):
                    print_cap(f"Daily message cap reached ({daily_cap}). Stopping.")
                    logger.warning("Daily message cap reached mid-run")
                    break

                progress.update(task, description=f"[{i+1}/{len(candidates)}] {url[-40:]}...")

                try:
                    if dry_run:
                        status = bot.dry_run_message(url, message_template)
                    else:
                        status = bot.send_followup_message(url, message_template)

                    if status == STATUS_MESSAGED:
                        if not dry_run:
                            db.update_status(url, STATUS_MESSAGED)
                            db.increment_daily_counter(COUNTER_MESSAGES)
                        messaged += 1
                        logger.info(f"MESSAGED | {url}")

                    elif status == "not_connected":
                        still_pending += 1
                        logger.info(f"NOT_YET_CONNECTED | {url}")

                    elif status == STATUS_SKIPPED:
                        if not dry_run:
                            db.update_status(url, STATUS_SKIPPED)
                        skipped += 1
                        logger.info(f"SKIPPED | {url}")

                    else:
                        if not dry_run:
                            db.update_status(url, STATUS_ERROR, error_msg=f"Message error: {status}")
                        errors += 1
                        logger.error(f"ERROR | {url} | {status}")

                    processed += 1

                except Exception as e:
                    if not dry_run:
                        db.update_status(url, STATUS_ERROR, error_msg=str(e)[:200])
                    errors += 1
                    processed += 1
                    logger.error(f"EXCEPTION | {url} | {e}")

                progress.update(task, advance=1)

                # Delay between profiles
                if i < len(candidates) - 1 and not _interrupted:
                    if bot.should_take_long_pause(processed):
                        if not dry_run:
                            bot.long_pause()
                    else:
                        if not dry_run:
                            if delay_override > 0:
                                time.sleep(delay_override)
                            else:
                                bot.profile_delay()

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print_error(f"Unexpected error: {e}")

    finally:
        bot.close()
        _bot_ref = None

    # Print session summary
    print_session_summary(
        mode="message",
        processed=processed,
        messaged=messaged,
        still_pending=still_pending,
        skipped=skipped,
        errors=errors,
        dry_run=dry_run,
    )
    logger.info(
        f"Message session done | processed={processed} messaged={messaged} "
        f"still_pending={still_pending} skipped={skipped} errors={errors}"
    )

    if not dry_run:
        summary = db.get_summary()
        print_db_summary(summary)

    db.close()
    _db_ref = None


# ─── Status Dashboard ───────────────────────────────────────────────────────

def show_status():
    """Display the rich status dashboard from the database."""
    db = Database()
    summary = db.get_summary()
    daily_connections = db.get_daily_count(COUNTER_CONNECTIONS)
    daily_messages = db.get_daily_count(COUNTER_MESSAGES)
    daily_stats = db.get_daily_stats()

    print_dashboard(summary, daily_connections, daily_messages, daily_stats)
    db.close()


# ─── CSV Export ──────────────────────────────────────────────────────────────

def export_csv(output_path: str):
    """
    Export all profiles from the database to a CSV file.

    Args:
        output_path: Path for the output CSV file.
    """
    logger = setup_logging()
    db = Database()
    profiles = db.get_all_profiles()

    if not profiles:
        print_info("No profiles in the database to export.")
        db.close()
        return

    fieldnames = ["id", "url", "name", "status", "error_msg", "created_at", "updated_at"]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(profiles)

    print_export_success(output_path, len(profiles))
    logger.info(f"Exported {len(profiles)} profiles to {output_path}")
    db.close()


# ─── CLI Entry Point ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Auto-Connect & Message Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --file urls.xlsx --mode connect           Send connection requests
  python main.py --file urls.xlsx --mode message           Send follow-up messages
  python main.py --file urls.xlsx --mode both              Connect then message
  python main.py --file urls.csv --mode connect --dry-run  Simulate without clicking
  python main.py --status                                  Show progress dashboard
  python main.py --reset-errors                            Retry failed profiles
  python main.py --export results.csv                      Export all profiles to CSV
        """,
    )

    parser.add_argument(
        "--file", "-f", type=str,
        help="Path to spreadsheet (CSV/XLSX) or Google Sheets URL",
    )
    parser.add_argument(
        "--mode", "-m", type=str, choices=["connect", "message", "both"],
        help="Operation mode: connect, message, or both",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate without sending requests or messages",
    )
    parser.add_argument(
        "--cap", type=int, default=0,
        help="Override daily cap for this run (connections or messages)",
    )
    parser.add_argument(
        "--delay", type=float, default=0,
        help="Override minimum delay (seconds) between profiles. 0 = use default",
    )
    parser.add_argument(
        "--status", "-s", action="store_true",
        help="Show progress dashboard",
    )
    parser.add_argument(
        "--reset-errors", action="store_true",
        help="Reset error profiles to pending for retry",
    )
    parser.add_argument(
        "--export", "-e", type=str, metavar="FILE",
        help="Export all profiles to CSV (e.g. --export results.csv)",
    )

    args = parser.parse_args()

    # ── Handle status display ──
    if args.status:
        show_status()
        return

    # ── Handle error reset ──
    if args.reset_errors:
        db = Database()
        count = db.reset_errors()
        if count > 0:
            print_success(f"Reset {count} error profiles back to pending.")
        else:
            print_info("No error profiles to reset.")
        db.close()
        return

    # ── Handle CSV export ──
    if args.export:
        export_csv(args.export)
        return

    # ── Require --file and --mode for automation ──
    if not args.file:
        parser.error("--file is required for automation (use --status for dashboard)")
    if not args.mode:
        parser.error("--mode is required (connect, message, or both)")

    # Validate file exists (unless Google Sheets URL)
    if not args.file.startswith("https://"):
        if not Path(args.file).exists():
            print_error(f"File not found: {args.file}")
            sys.exit(1)

    # ── Run the selected mode ──
    if args.mode == "connect":
        run_connect(args.file, dry_run=args.dry_run, cap=args.cap, delay_override=args.delay)

    elif args.mode == "message":
        run_message(args.file, dry_run=args.dry_run, cap=args.cap, delay_override=args.delay)

    elif args.mode == "both":
        print_info("Running connect mode first...")
        run_connect(args.file, dry_run=args.dry_run, cap=args.cap, delay_override=args.delay)
        console.print()
        print_info("Now running message mode for accepted connections...")
        run_message(args.file, dry_run=args.dry_run, cap=args.cap, delay_override=args.delay)


if __name__ == "__main__":
    main()
