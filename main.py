"""
main.py — CLI entry point for the LinkedIn Auto-Connect & Message Tool.

Usage:
    python main.py --file urls.xlsx --mode connect
    python main.py --file urls.csv --mode connect --dry-run
    python main.py --status
"""

import argparse
import sys
import time
from pathlib import Path

from config import (
    DAILY_CONNECTION_CAP,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_SKIPPED,
    get_connection_note_template,
)
from db import COUNTER_CONNECTIONS, Database
from linkedin_bot import LinkedInBot, LinkedInCapReachedError, SessionExpiredError
from spreadsheet_reader import read_spreadsheet


def run_connect(file_path: str, dry_run: bool = False, cap: int = 0):
    """
    Run the connection request workflow.

    Reads URLs from spreadsheet, imports to DB, then processes pending profiles
    one by one — visiting each and sending a personalized connection request.

    Args:
        file_path: Path to CSV/XLSX/Google Sheets URL with LinkedIn profile URLs.
        dry_run: If True, visit profiles but don't click any buttons.
        cap: Override daily connection cap. 0 = use default from config.
    """
    daily_cap = cap if cap > 0 else DAILY_CONNECTION_CAP

    # Step 1: Read spreadsheet and import URLs
    print(f"\n{'='*60}")
    print(f"  LinkedIn Auto-Connect Tool {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}\n")

    urls = read_spreadsheet(file_path)
    if not urls:
        print("[ERROR] No valid LinkedIn URLs found in the file.")
        return

    db = Database()
    import_result = db.import_urls(urls)
    print(f"[DB] Imported {import_result['imported']} new URLs, "
          f"skipped {import_result['skipped']} duplicates.\n")

    # Step 2: Check daily cap
    if db.is_daily_cap_reached(COUNTER_CONNECTIONS):
        today_count = db.get_daily_count(COUNTER_CONNECTIONS)
        print(f"[CAP] Daily connection cap reached ({today_count}/{daily_cap}). "
              f"Try again tomorrow.")
        db.close()
        return

    # Step 3: Get pending profiles
    remaining_today = daily_cap - db.get_daily_count(COUNTER_CONNECTIONS)
    pending = db.get_pending_profiles(limit=remaining_today)

    if not pending:
        print("[INFO] No pending profiles to process.")
        summary = db.get_summary()
        print(f"[INFO] Summary: {summary}")
        db.close()
        return

    print(f"[INFO] Processing {len(pending)} profiles (daily cap: {daily_cap}, "
          f"remaining: {remaining_today})\n")

    # Step 4: Load template
    try:
        note_template = get_connection_note_template()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}")
        db.close()
        return

    # Step 5: Launch browser and start processing
    bot = LinkedInBot()

    try:
        logged_in = bot.start()

        if not logged_in:
            bot.login()
            if not bot.is_logged_in():
                print("[ERROR] Login failed. Please try again.")
                bot.close()
                db.close()
                return

        # Stats for this session
        processed = 0
        sent = 0
        skipped = 0
        errors = 0

        for i, profile in enumerate(pending):
            url = profile["url"]
            print(f"\n[{i+1}/{len(pending)}] {url}")

            # Check daily cap before each profile
            if db.is_daily_cap_reached(COUNTER_CONNECTIONS):
                print(f"\n[CAP] Daily connection cap reached ({daily_cap}). Stopping.")
                break

            try:
                if dry_run:
                    status = bot.dry_run_connection(url, note_template)
                else:
                    status = bot.send_connection_request(url, note_template)

                # Update DB based on result
                if status == STATUS_REQUEST_SENT:
                    name_info = None
                    try:
                        # Name was already printed, extract from page
                        name_el = bot.page.query_selector("h1")
                        if name_el:
                            name_info = name_el.inner_text().strip()
                    except Exception:
                        pass

                    if not dry_run:
                        db.update_status(url, STATUS_REQUEST_SENT, name=name_info)
                        db.increment_daily_counter(COUNTER_CONNECTIONS)
                    sent += 1
                    print(f"[BOT]   ✓ Request sent")

                elif status == "already_connected":
                    if not dry_run:
                        db.update_status(url, "connected", name=name_info if 'name_info' in dir() else None)
                    print(f"[BOT]   ○ Already connected")
                    skipped += 1

                elif status == "already_pending":
                    if not dry_run:
                        db.update_status(url, STATUS_REQUEST_SENT)
                    print(f"[BOT]   ○ Already pending")
                    skipped += 1

                elif status == STATUS_SKIPPED:
                    if not dry_run:
                        db.update_status(url, STATUS_SKIPPED)
                    print(f"[BOT]   ○ Skipped (no Connect button)")
                    skipped += 1

                elif status == "cap_reached":
                    print(f"\n[CAP] LinkedIn weekly invitation limit reached!")
                    if not dry_run:
                        db.update_status(url, STATUS_PENDING)  # Keep as pending for retry
                    break

                else:  # error
                    if not dry_run:
                        db.update_status(url, STATUS_ERROR, error_msg=f"Status: {status}")
                    errors += 1
                    print(f"[BOT]   ✗ Error")

                processed += 1

            except KeyboardInterrupt:
                print(f"\n\n[INTERRUPTED] Stopping gracefully...")
                break

            except Exception as e:
                print(f"[BOT]   ✗ Unexpected error: {e}")
                if not dry_run:
                    db.update_status(url, STATUS_ERROR, error_msg=str(e)[:200])
                errors += 1
                processed += 1

            # Delay between profiles
            if i < len(pending) - 1:
                if bot.should_take_long_pause(processed):
                    if not dry_run:
                        bot.long_pause()
                    else:
                        print("[DRY RUN] Would take a long pause here")
                else:
                    if not dry_run:
                        bot.profile_delay()
                    else:
                        print("[DRY RUN] Would delay before next profile")

        # Print session summary
        print(f"\n{'='*60}")
        print(f"  Session Summary {'(DRY RUN)' if dry_run else ''}")
        print(f"{'='*60}")
        print(f"  Processed: {processed}")
        print(f"  Sent:      {sent}")
        print(f"  Skipped:   {skipped}")
        print(f"  Errors:    {errors}")

        if not dry_run:
            summary = db.get_summary()
            print(f"\n  Database Status:")
            for status, count in summary.items():
                if count > 0:
                    print(f"    {status}: {count}")

        print(f"{'='*60}\n")

    except KeyboardInterrupt:
        print(f"\n\n[INTERRUPTED] Shutting down...")

    finally:
        bot.close()
        db.close()


def show_status():
    """Display the current progress summary from the database."""
    db = Database()
    summary = db.get_summary()
    daily_connections = db.get_daily_count(COUNTER_CONNECTIONS)

    print(f"\n{'='*60}")
    print(f"  LinkedIn Auto-Connect — Status Dashboard")
    print(f"{'='*60}\n")

    print(f"  {'Status':<20} {'Count':>8}")
    print(f"  {'─'*20} {'─'*8}")
    for status, count in summary.items():
        if status == "total":
            print(f"  {'─'*20} {'─'*8}")
        print(f"  {status:<20} {count:>8}")

    print(f"\n  Today's connections sent: {daily_connections}/{DAILY_CONNECTION_CAP}")

    daily_stats = db.get_daily_stats()
    if daily_stats:
        print(f"\n  Recent Activity:")
        for day in daily_stats[:7]:
            print(f"    {day['date']}: {day['connections_sent']} connects, "
                  f"{day['messages_sent']} messages")

    print(f"\n{'='*60}\n")
    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn Auto-Connect & Message Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --file urls.xlsx --mode connect           Send connection requests
  python main.py --file urls.csv --mode connect --dry-run  Simulate without clicking
  python main.py --status                                  Show progress dashboard
  python main.py --reset-errors                            Retry failed profiles
        """,
    )

    parser.add_argument("--file", "-f", type=str, help="Path to spreadsheet (CSV/XLSX) or Google Sheets URL")
    parser.add_argument("--mode", "-m", type=str, choices=["connect", "message", "both"],
                       help="Operation mode: connect, message, or both")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without sending requests")
    parser.add_argument("--cap", type=int, default=0, help="Override daily connection cap for this run")
    parser.add_argument("--status", "-s", action="store_true", help="Show progress dashboard")
    parser.add_argument("--reset-errors", action="store_true", help="Reset error profiles to pending")

    args = parser.parse_args()

    # Handle status display
    if args.status:
        show_status()
        return

    # Handle error reset
    if args.reset_errors:
        db = Database()
        count = db.reset_errors()
        print(f"[DB] Reset {count} error profiles back to pending.")
        db.close()
        return

    # Require --file and --mode for automation
    if not args.file:
        parser.error("--file is required for automation (use --status for dashboard)")
    if not args.mode:
        parser.error("--mode is required (connect, message, or both)")

    # Validate file exists (unless Google Sheets URL)
    if not args.file.startswith("https://"):
        if not Path(args.file).exists():
            print(f"[ERROR] File not found: {args.file}")
            sys.exit(1)

    # Run the selected mode
    if args.mode == "connect":
        run_connect(args.file, dry_run=args.dry_run, cap=args.cap)
    elif args.mode == "message":
        print("[INFO] Message mode will be available in Phase 5.")
    elif args.mode == "both":
        print("[INFO] Running connect mode first...")
        run_connect(args.file, dry_run=args.dry_run, cap=args.cap)
        print("[INFO] Message mode will be available in Phase 5.")


if __name__ == "__main__":
    main()
