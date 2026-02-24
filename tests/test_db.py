"""
tests/test_db.py — Unit tests for the SQLite database layer.
All tests use an in-memory database for speed and isolation.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import COUNTER_CONNECTIONS, COUNTER_MESSAGES, Database
from config import (
    DAILY_CONNECTION_CAP,
    DAILY_MESSAGE_CAP,
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_MESSAGED,
    STATUS_PENDING,
    STATUS_REQUEST_SENT,
    STATUS_SKIPPED,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    """Create a fresh in-memory database for each test."""
    database = Database(db_path=":memory:")
    yield database
    database.close()


@pytest.fixture
def sample_urls():
    """Sample URL list matching spreadsheet_reader output format."""
    return [
        {"url": "https://www.linkedin.com/in/johndoe", "row": 2},
        {"url": "https://www.linkedin.com/in/janedoe", "row": 3},
        {"url": "https://www.linkedin.com/in/bobsmith", "row": 4},
        {"url": "https://www.linkedin.com/in/alicejones", "row": 5},
        {"url": "https://www.linkedin.com/in/charlie", "row": 6},
    ]


# ─── Context Manager ────────────────────────────────────────────────────────


class TestContextManager:
    def test_context_manager(self):
        with Database(db_path=":memory:") as db:
            assert db.conn is not None
        assert db.conn is None

    def test_close_idempotent(self, db):
        db.close()
        db.close()  # Should not raise


# ─── Import URLs ─────────────────────────────────────────────────────────────


class TestImportURLs:
    def test_import_urls(self, db, sample_urls):
        result = db.import_urls(sample_urls)
        assert result["imported"] == 5
        assert result["skipped"] == 0
        assert result["total"] == 5

    def test_import_skips_duplicates(self, db, sample_urls):
        db.import_urls(sample_urls)
        result = db.import_urls(sample_urls)
        assert result["imported"] == 0
        assert result["skipped"] == 5
        assert result["total"] == 5

    def test_import_partial_duplicates(self, db, sample_urls):
        db.import_urls(sample_urls[:3])
        result = db.import_urls(sample_urls)
        assert result["imported"] == 2
        assert result["skipped"] == 3

    def test_import_empty_list(self, db):
        result = db.import_urls([])
        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert result["total"] == 0

    def test_imported_profiles_are_pending(self, db, sample_urls):
        db.import_urls(sample_urls)
        profiles = db.get_pending_profiles()
        assert len(profiles) == 5
        assert all(p["status"] == STATUS_PENDING for p in profiles)


# ─── Query Profiles ─────────────────────────────────────────────────────────


class TestQueryProfiles:
    def test_get_pending_profiles(self, db, sample_urls):
        db.import_urls(sample_urls)
        profiles = db.get_pending_profiles()
        assert len(profiles) == 5
        assert all(p["status"] == STATUS_PENDING for p in profiles)

    def test_get_pending_profiles_with_limit(self, db, sample_urls):
        db.import_urls(sample_urls)
        profiles = db.get_pending_profiles(limit=3)
        assert len(profiles) == 3

    def test_get_pending_profiles_empty(self, db):
        profiles = db.get_pending_profiles()
        assert profiles == []

    def test_get_profiles_by_status(self, db, sample_urls):
        db.import_urls(sample_urls)
        db.update_status(sample_urls[0]["url"], STATUS_REQUEST_SENT)
        db.update_status(sample_urls[1]["url"], STATUS_REQUEST_SENT)

        sent = db.get_profiles_by_status(STATUS_REQUEST_SENT)
        assert len(sent) == 2

        pending = db.get_profiles_by_status(STATUS_PENDING)
        assert len(pending) == 3

    def test_get_accepted_profiles(self, db, sample_urls):
        db.import_urls(sample_urls)
        db.update_status(sample_urls[0]["url"], STATUS_REQUEST_SENT)
        db.update_status(sample_urls[1]["url"], STATUS_REQUEST_SENT)

        accepted = db.get_accepted_profiles()
        assert len(accepted) == 2
        assert all(p["status"] == STATUS_REQUEST_SENT for p in accepted)

    def test_get_accepted_profiles_with_limit(self, db, sample_urls):
        db.import_urls(sample_urls)
        for url_data in sample_urls:
            db.update_status(url_data["url"], STATUS_REQUEST_SENT)

        accepted = db.get_accepted_profiles(limit=2)
        assert len(accepted) == 2

    def test_get_profile_by_url(self, db, sample_urls):
        db.import_urls(sample_urls)
        profile = db.get_profile_by_url(sample_urls[0]["url"])
        assert profile is not None
        assert profile["url"] == sample_urls[0]["url"]
        assert profile["status"] == STATUS_PENDING

    def test_get_profile_by_url_not_found(self, db):
        profile = db.get_profile_by_url("https://linkedin.com/in/nonexistent")
        assert profile is None

    def test_profiles_ordered_by_id(self, db, sample_urls):
        db.import_urls(sample_urls)
        profiles = db.get_pending_profiles()
        urls = [p["url"] for p in profiles]
        assert urls == [u["url"] for u in sample_urls]


# ─── Update Status ───────────────────────────────────────────────────────────


class TestUpdateStatus:
    def test_update_status(self, db, sample_urls):
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        db.update_status(url, STATUS_REQUEST_SENT)
        profile = db.get_profile_by_url(url)
        assert profile["status"] == STATUS_REQUEST_SENT

    def test_update_status_with_name(self, db, sample_urls):
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        db.update_status(url, STATUS_REQUEST_SENT, name="John Doe")
        profile = db.get_profile_by_url(url)
        assert profile["status"] == STATUS_REQUEST_SENT
        assert profile["name"] == "John Doe"

    def test_update_status_with_error(self, db, sample_urls):
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        db.update_status(url, STATUS_ERROR, error_msg="Profile not found")
        profile = db.get_profile_by_url(url)
        assert profile["status"] == STATUS_ERROR
        assert profile["error_msg"] == "Profile not found"

    def test_update_status_with_name_and_error(self, db, sample_urls):
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        db.update_status(url, STATUS_ERROR, name="John Doe", error_msg="Timeout")
        profile = db.get_profile_by_url(url)
        assert profile["status"] == STATUS_ERROR
        assert profile["name"] == "John Doe"
        assert profile["error_msg"] == "Timeout"

    def test_status_transitions(self, db, sample_urls):
        """Test the full lifecycle: pending → request_sent → connected → messaged."""
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        db.update_status(url, STATUS_REQUEST_SENT, name="John")
        assert db.get_profile_by_url(url)["status"] == STATUS_REQUEST_SENT

        db.update_status(url, STATUS_CONNECTED)
        assert db.get_profile_by_url(url)["status"] == STATUS_CONNECTED

        db.update_status(url, STATUS_MESSAGED)
        assert db.get_profile_by_url(url)["status"] == STATUS_MESSAGED

    def test_update_sets_updated_at(self, db, sample_urls):
        db.import_urls(sample_urls)
        url = sample_urls[0]["url"]

        before = db.get_profile_by_url(url)["updated_at"]
        db.update_status(url, STATUS_REQUEST_SENT)
        after = db.get_profile_by_url(url)["updated_at"]

        # updated_at should be set (may be same second, so just check it's not None)
        assert after is not None


# ─── Reset Errors ────────────────────────────────────────────────────────────


class TestResetErrors:
    def test_reset_errors(self, db, sample_urls):
        db.import_urls(sample_urls)
        db.update_status(sample_urls[0]["url"], STATUS_ERROR, error_msg="fail1")
        db.update_status(sample_urls[1]["url"], STATUS_ERROR, error_msg="fail2")
        db.update_status(sample_urls[2]["url"], STATUS_REQUEST_SENT)

        count = db.reset_errors()
        assert count == 2

        # Those two should now be pending again
        p0 = db.get_profile_by_url(sample_urls[0]["url"])
        assert p0["status"] == STATUS_PENDING
        assert p0["error_msg"] is None

        p1 = db.get_profile_by_url(sample_urls[1]["url"])
        assert p1["status"] == STATUS_PENDING

        # The request_sent one should be untouched
        p2 = db.get_profile_by_url(sample_urls[2]["url"])
        assert p2["status"] == STATUS_REQUEST_SENT

    def test_reset_errors_none(self, db, sample_urls):
        db.import_urls(sample_urls)
        count = db.reset_errors()
        assert count == 0


# ─── Daily Counters ──────────────────────────────────────────────────────────


class TestDailyCounters:
    def test_initial_count_is_zero(self, db):
        assert db.get_daily_count(COUNTER_CONNECTIONS) == 0
        assert db.get_daily_count(COUNTER_MESSAGES) == 0

    def test_increment_connections(self, db):
        db.increment_daily_counter(COUNTER_CONNECTIONS)
        assert db.get_daily_count(COUNTER_CONNECTIONS) == 1

        db.increment_daily_counter(COUNTER_CONNECTIONS)
        assert db.get_daily_count(COUNTER_CONNECTIONS) == 2

    def test_increment_messages(self, db):
        db.increment_daily_counter(COUNTER_MESSAGES)
        db.increment_daily_counter(COUNTER_MESSAGES)
        db.increment_daily_counter(COUNTER_MESSAGES)
        assert db.get_daily_count(COUNTER_MESSAGES) == 3

    def test_counters_independent(self, db):
        db.increment_daily_counter(COUNTER_CONNECTIONS)
        db.increment_daily_counter(COUNTER_CONNECTIONS)
        db.increment_daily_counter(COUNTER_MESSAGES)

        assert db.get_daily_count(COUNTER_CONNECTIONS) == 2
        assert db.get_daily_count(COUNTER_MESSAGES) == 1

    def test_invalid_counter_type_raises(self, db):
        with pytest.raises(ValueError):
            db.increment_daily_counter("invalid_type")

        with pytest.raises(ValueError):
            db.get_daily_count("invalid_type")

    def test_daily_cap_not_reached(self, db):
        assert db.is_daily_cap_reached(COUNTER_CONNECTIONS) is False
        assert db.is_daily_cap_reached(COUNTER_MESSAGES) is False

    def test_daily_connection_cap_reached(self, db):
        for _ in range(DAILY_CONNECTION_CAP):
            db.increment_daily_counter(COUNTER_CONNECTIONS)

        assert db.is_daily_cap_reached(COUNTER_CONNECTIONS) is True

    def test_daily_message_cap_reached(self, db):
        for _ in range(DAILY_MESSAGE_CAP):
            db.increment_daily_counter(COUNTER_MESSAGES)

        assert db.is_daily_cap_reached(COUNTER_MESSAGES) is True

    def test_daily_cap_just_below(self, db):
        for _ in range(DAILY_CONNECTION_CAP - 1):
            db.increment_daily_counter(COUNTER_CONNECTIONS)

        assert db.is_daily_cap_reached(COUNTER_CONNECTIONS) is False

    def test_invalid_cap_type_raises(self, db):
        with pytest.raises(ValueError):
            db.is_daily_cap_reached("invalid_type")


# ─── Summary ─────────────────────────────────────────────────────────────────


class TestSummary:
    def test_empty_summary(self, db):
        summary = db.get_summary()
        assert summary["total"] == 0
        assert summary[STATUS_PENDING] == 0

    def test_summary_counts(self, db, sample_urls):
        db.import_urls(sample_urls)
        db.update_status(sample_urls[0]["url"], STATUS_REQUEST_SENT)
        db.update_status(sample_urls[1]["url"], STATUS_REQUEST_SENT)
        db.update_status(sample_urls[2]["url"], STATUS_ERROR, error_msg="oops")

        summary = db.get_summary()
        assert summary[STATUS_PENDING] == 2
        assert summary[STATUS_REQUEST_SENT] == 2
        assert summary[STATUS_ERROR] == 1
        assert summary["total"] == 5

    def test_summary_all_statuses_present(self, db):
        summary = db.get_summary()
        for status in [STATUS_PENDING, STATUS_REQUEST_SENT, STATUS_CONNECTED,
                       STATUS_MESSAGED, STATUS_SKIPPED, STATUS_ERROR]:
            assert status in summary


# ─── Export ──────────────────────────────────────────────────────────────────


class TestExport:
    def test_get_all_profiles(self, db, sample_urls):
        db.import_urls(sample_urls)
        all_profiles = db.get_all_profiles()
        assert len(all_profiles) == 5
        assert all("url" in p for p in all_profiles)
        assert all("status" in p for p in all_profiles)
        assert all("created_at" in p for p in all_profiles)

    def test_get_all_profiles_empty(self, db):
        all_profiles = db.get_all_profiles()
        assert all_profiles == []

    def test_get_daily_stats(self, db):
        db.increment_daily_counter(COUNTER_CONNECTIONS)
        db.increment_daily_counter(COUNTER_MESSAGES)

        stats = db.get_daily_stats()
        assert len(stats) == 1
        assert stats[0]["date"] == date.today().isoformat()
        assert stats[0]["connections_sent"] == 1
        assert stats[0]["messages_sent"] == 1

    def test_get_daily_stats_empty(self, db):
        stats = db.get_daily_stats()
        assert stats == []
