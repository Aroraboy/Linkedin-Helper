"""
db.py — SQLite persistence layer for tracking profile statuses and daily caps.

Tables:
    profiles       — One row per LinkedIn profile URL with status tracking.
    daily_counters — Tracks how many connections/messages were sent each day.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from config import (
    ALL_STATUSES,
    DAILY_CONNECTION_CAP,
    DAILY_MESSAGE_CAP,
    DB_PATH,
    STATUS_ERROR,
    STATUS_MESSAGED,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
)

# Counter types
COUNTER_CONNECTIONS = "connections_sent"
COUNTER_MESSAGES = "messages_sent"


class Database:
    """
    SQLite database for persisting LinkedIn automation progress.

    Usage:
        with Database() as db:
            db.import_urls([{"url": "https://linkedin.com/in/john", "row": 1}])
            pending = db.get_pending_profiles(limit=20)
            db.update_status(url, "request_sent", name="John Doe")
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the database connection and create tables if they don't exist.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to config.DB_PATH ("progress.db").
                     Use ":memory:" for in-memory testing.
        """
        self.db_path = str(db_path) if db_path else str(DB_PATH)
        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._create_tables()

    def _connect(self):
        """Establish database connection with optimized settings."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        self.conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        self.conn.execute("PRAGMA foreign_keys=ON")

    def _create_tables(self):
        """Create tables if they don't already exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                url         TEXT    UNIQUE NOT NULL,
                name        TEXT    DEFAULT NULL,
                status      TEXT    NOT NULL DEFAULT 'pending',
                error_msg   TEXT    DEFAULT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_profiles_status ON profiles(status);
            CREATE INDEX IF NOT EXISTS idx_profiles_url    ON profiles(url);

            CREATE TABLE IF NOT EXISTS daily_counters (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                date             TEXT    NOT NULL,
                connections_sent INTEGER NOT NULL DEFAULT 0,
                messages_sent    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(date)
            );
        """)
        self.conn.commit()

    # ─── Context Manager ─────────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    # ─── Import URLs ─────────────────────────────────────────────────────────

    def import_urls(self, urls: list[dict]) -> dict:
        """
        Bulk-import profile URLs into the database.
        Skips duplicates (URLs already in the database).

        Args:
            urls: List of dicts from spreadsheet_reader, e.g.
                  [{"url": "https://linkedin.com/in/john", "row": 1}, ...]

        Returns:
            dict with counts: {"imported": N, "skipped": N, "total": N}
        """
        imported = 0
        skipped = 0

        for item in urls:
            url = item["url"]
            try:
                self.conn.execute(
                    "INSERT INTO profiles (url, status) VALUES (?, ?)",
                    (url, STATUS_PENDING),
                )
                imported += 1
            except sqlite3.IntegrityError:
                # URL already exists — skip
                skipped += 1

        self.conn.commit()
        return {"imported": imported, "skipped": skipped, "total": len(urls)}

    # ─── Query Profiles ──────────────────────────────────────────────────────

    def get_pending_profiles(self, limit: int = 0) -> list[dict]:
        """
        Fetch profiles with status 'pending' (not yet processed).

        Args:
            limit: Maximum number of profiles to return. 0 = no limit.

        Returns:
            List of dicts: [{"id": 1, "url": "...", "name": None, "status": "pending"}, ...]
        """
        query = "SELECT id, url, name, status FROM profiles WHERE status = ? ORDER BY id"
        params: list = [STATUS_PENDING]

        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_profiles_by_status(self, status: str, limit: int = 0) -> list[dict]:
        """
        Fetch profiles with a specific status.

        Args:
            status: One of the STATUS_* constants from config.py.
            limit: Maximum number of profiles to return. 0 = no limit.

        Returns:
            List of dicts with profile data.
        """
        query = "SELECT id, url, name, status, error_msg FROM profiles WHERE status = ? ORDER BY id"
        params: list = [status]

        if limit > 0:
            query += " LIMIT ?"
            params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_accepted_profiles(self, limit: int = 0) -> list[dict]:
        """
        Fetch profiles with status 'request_sent' — candidates for follow-up messaging.
        (These are profiles where we sent a connection request but haven't messaged yet.)

        Args:
            limit: Maximum number of profiles to return. 0 = no limit.

        Returns:
            List of dicts with profile data.
        """
        return self.get_profiles_by_status(STATUS_REQUEST_SENT, limit)

    def get_profile_by_url(self, url: str) -> Optional[dict]:
        """
        Fetch a single profile by its URL.

        Returns:
            Dict with profile data, or None if not found.
        """
        row = self.conn.execute(
            "SELECT id, url, name, status, error_msg, created_at, updated_at "
            "FROM profiles WHERE url = ?",
            (url,),
        ).fetchone()
        return dict(row) if row else None

    # ─── Update Status ───────────────────────────────────────────────────────

    def update_status(
        self,
        url: str,
        status: str,
        name: Optional[str] = None,
        error_msg: Optional[str] = None,
    ):
        """
        Update the status of a profile.

        Args:
            url: The LinkedIn profile URL.
            status: New status (one of STATUS_* constants).
            name: Optional — the person's name scraped from their profile.
            error_msg: Optional — error message if status is 'error'.
        """
        if name and error_msg:
            self.conn.execute(
                "UPDATE profiles SET status = ?, name = ?, error_msg = ?, "
                "updated_at = datetime('now') WHERE url = ?",
                (status, name, error_msg, url),
            )
        elif name:
            self.conn.execute(
                "UPDATE profiles SET status = ?, name = ?, "
                "updated_at = datetime('now') WHERE url = ?",
                (status, name, url),
            )
        elif error_msg:
            self.conn.execute(
                "UPDATE profiles SET status = ?, error_msg = ?, "
                "updated_at = datetime('now') WHERE url = ?",
                (status, error_msg, url),
            )
        else:
            self.conn.execute(
                "UPDATE profiles SET status = ?, updated_at = datetime('now') WHERE url = ?",
                (status, url),
            )
        self.conn.commit()

    def reset_errors(self) -> int:
        """
        Reset all profiles with status 'error' back to 'pending' for retry.

        Returns:
            Number of profiles reset.
        """
        cursor = self.conn.execute(
            "UPDATE profiles SET status = ?, error_msg = NULL, "
            "updated_at = datetime('now') WHERE status = ?",
            (STATUS_PENDING, STATUS_ERROR),
        )
        self.conn.commit()
        return cursor.rowcount

    # ─── Daily Counters ──────────────────────────────────────────────────────

    def _ensure_daily_row(self):
        """Ensure today's row exists in the daily_counters table."""
        today = date.today().isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO daily_counters (date) VALUES (?)",
            (today,),
        )
        self.conn.commit()

    def increment_daily_counter(self, counter_type: str):
        """
        Increment today's counter for connections or messages.

        Args:
            counter_type: Either COUNTER_CONNECTIONS or COUNTER_MESSAGES.
        """
        if counter_type not in (COUNTER_CONNECTIONS, COUNTER_MESSAGES):
            raise ValueError(
                f"Invalid counter type: {counter_type}. "
                f"Use '{COUNTER_CONNECTIONS}' or '{COUNTER_MESSAGES}'."
            )

        self._ensure_daily_row()
        today = date.today().isoformat()
        self.conn.execute(
            f"UPDATE daily_counters SET {counter_type} = {counter_type} + 1 WHERE date = ?",
            (today,),
        )
        self.conn.commit()

    def get_daily_count(self, counter_type: str) -> int:
        """
        Get today's count for a specific counter.

        Args:
            counter_type: Either COUNTER_CONNECTIONS or COUNTER_MESSAGES.

        Returns:
            Today's count for the given counter type.
        """
        if counter_type not in (COUNTER_CONNECTIONS, COUNTER_MESSAGES):
            raise ValueError(f"Invalid counter type: {counter_type}")

        today = date.today().isoformat()
        row = self.conn.execute(
            f"SELECT {counter_type} FROM daily_counters WHERE date = ?",
            (today,),
        ).fetchone()

        return row[0] if row else 0

    def is_daily_cap_reached(self, counter_type: str) -> bool:
        """
        Check if today's daily cap has been reached.

        Args:
            counter_type: Either COUNTER_CONNECTIONS or COUNTER_MESSAGES.

        Returns:
            True if the daily cap is reached, False otherwise.
        """
        count = self.get_daily_count(counter_type)

        if counter_type == COUNTER_CONNECTIONS:
            return count >= DAILY_CONNECTION_CAP
        elif counter_type == COUNTER_MESSAGES:
            return count >= DAILY_MESSAGE_CAP
        else:
            raise ValueError(f"Invalid counter type: {counter_type}")

    # ─── Summary & Export ────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        """
        Get a summary of profile counts grouped by status.

        Returns:
            dict: {"pending": 900, "request_sent": 50, "connected": 30, ...}
        """
        summary = {status: 0 for status in ALL_STATUSES}

        rows = self.conn.execute(
            "SELECT status, COUNT(*) as count FROM profiles GROUP BY status"
        ).fetchall()

        for row in rows:
            summary[row["status"]] = row["count"]

        summary["total"] = sum(summary.values())
        return summary

    def get_all_profiles(self) -> list[dict]:
        """
        Fetch all profiles with full data (for export).

        Returns:
            List of dicts with all profile columns.
        """
        rows = self.conn.execute(
            "SELECT id, url, name, status, error_msg, created_at, updated_at "
            "FROM profiles ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_daily_stats(self) -> list[dict]:
        """
        Fetch all daily counter records (for analytics).

        Returns:
            List of dicts: [{"date": "2026-02-24", "connections_sent": 20, "messages_sent": 10}, ...]
        """
        rows = self.conn.execute(
            "SELECT date, connections_sent, messages_sent "
            "FROM daily_counters ORDER BY date DESC"
        ).fetchall()
        return [dict(row) for row in rows]
