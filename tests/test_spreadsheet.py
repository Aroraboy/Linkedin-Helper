"""
tests/test_spreadsheet.py — Unit tests for the spreadsheet reader module.
"""

import csv
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from spreadsheet_reader import (
    LINKEDIN_URL_PATTERN,
    _clean_url,
    _find_url_column,
    _validate_url,
    read_csv,
    read_spreadsheet,
    read_xlsx,
)


# ─── URL Validation Tests ────────────────────────────────────────────────────


class TestURLValidation:
    """Tests for LinkedIn URL validation."""

    def test_valid_url_standard(self):
        assert LINKEDIN_URL_PATTERN.match("https://www.linkedin.com/in/johndoe")

    def test_valid_url_without_www(self):
        assert LINKEDIN_URL_PATTERN.match("https://linkedin.com/in/johndoe")

    def test_valid_url_with_trailing_slash(self):
        assert LINKEDIN_URL_PATTERN.match("https://www.linkedin.com/in/johndoe/")

    def test_valid_url_with_hyphens(self):
        assert LINKEDIN_URL_PATTERN.match("https://www.linkedin.com/in/john-doe-123")

    def test_valid_url_with_query_params(self):
        assert LINKEDIN_URL_PATTERN.match(
            "https://www.linkedin.com/in/johndoe?trk=something"
        )

    def test_valid_url_http(self):
        assert LINKEDIN_URL_PATTERN.match("http://www.linkedin.com/in/johndoe")

    def test_invalid_url_company_page(self):
        assert not LINKEDIN_URL_PATTERN.match(
            "https://www.linkedin.com/company/google"
        )

    def test_invalid_url_random(self):
        assert not LINKEDIN_URL_PATTERN.match("https://www.google.com")

    def test_invalid_url_empty(self):
        assert not LINKEDIN_URL_PATTERN.match("")

    def test_invalid_url_partial(self):
        assert not LINKEDIN_URL_PATTERN.match("linkedin.com/in/johndoe")


class TestCleanURL:
    """Tests for URL cleaning."""

    def test_strips_whitespace(self):
        assert _clean_url("  https://www.linkedin.com/in/johndoe  ") == "https://www.linkedin.com/in/johndoe"

    def test_removes_trailing_slash(self):
        assert _clean_url("https://www.linkedin.com/in/johndoe/") == "https://www.linkedin.com/in/johndoe"

    def test_no_change_needed(self):
        assert _clean_url("https://www.linkedin.com/in/johndoe") == "https://www.linkedin.com/in/johndoe"


class TestValidateURL:
    """Tests for the _validate_url helper."""

    def test_valid_url_returns_cleaned(self):
        result = _validate_url("https://www.linkedin.com/in/johndoe", 1)
        assert result == "https://www.linkedin.com/in/johndoe"

    def test_url_without_protocol_gets_fixed(self):
        result = _validate_url("www.linkedin.com/in/johndoe", 1)
        assert result == "https://www.linkedin.com/in/johndoe"

    def test_url_without_www_or_protocol_gets_fixed(self):
        result = _validate_url("linkedin.com/in/johndoe", 1)
        assert result == "https://linkedin.com/in/johndoe"

    def test_invalid_url_returns_none(self):
        result = _validate_url("https://google.com", 1)
        assert result is None

    def test_empty_url_returns_none(self):
        result = _validate_url("", 1)
        assert result is None


class TestFindURLColumn:
    """Tests for header-based URL column detection."""

    def test_finds_url_column(self):
        assert _find_url_column(["Name", "URL", "Company"]) == 1

    def test_finds_link_column(self):
        assert _find_url_column(["Name", "LinkedIn Link", "Company"]) == 1

    def test_finds_linkedin_column(self):
        assert _find_url_column(["Name", "LinkedIn", "Company"]) == 1

    def test_finds_profile_column(self):
        assert _find_url_column(["Name", "Profile URL", "Company"]) == 1

    def test_returns_none_when_not_found(self):
        assert _find_url_column(["Name", "Email", "Company"]) is None

    def test_case_insensitive(self):
        assert _find_url_column(["name", "LINKEDIN URL", "company"]) == 1


# ─── CSV Reader Tests ────────────────────────────────────────────────────────


class TestReadCSV:
    """Tests for CSV file reading."""

    def _create_csv(self, rows: list[list[str]], tmpdir: str) -> str:
        """Helper to create a temporary CSV file."""
        path = os.path.join(tmpdir, "test.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        return path

    def test_csv_with_header(self, tmp_path):
        path = self._create_csv(
            [
                ["Name", "LinkedIn URL", "Company"],
                ["John", "https://www.linkedin.com/in/johndoe", "Acme"],
                ["Jane", "https://www.linkedin.com/in/janedoe", "Beta"],
            ],
            str(tmp_path),
        )
        results = read_csv(path)
        assert len(results) == 2
        assert results[0]["url"] == "https://www.linkedin.com/in/johndoe"
        assert results[0]["row"] == 2
        assert results[1]["url"] == "https://www.linkedin.com/in/janedoe"
        assert results[1]["row"] == 3

    def test_csv_without_header(self, tmp_path):
        path = self._create_csv(
            [
                ["https://www.linkedin.com/in/johndoe"],
                ["https://www.linkedin.com/in/janedoe"],
            ],
            str(tmp_path),
        )
        results = read_csv(path)
        assert len(results) == 2

    def test_csv_with_invalid_urls(self, tmp_path):
        path = self._create_csv(
            [
                ["LinkedIn URL"],
                ["https://www.linkedin.com/in/johndoe"],
                ["https://www.google.com"],
                ["https://www.linkedin.com/in/janedoe"],
            ],
            str(tmp_path),
        )
        results = read_csv(path)
        assert len(results) == 2  # Invalid URL skipped

    def test_csv_empty_file_raises(self, tmp_path):
        path = os.path.join(str(tmp_path), "empty.csv")
        with open(path, "w") as f:
            pass
        with pytest.raises(ValueError, match="empty"):
            read_csv(path)

    def test_csv_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_csv("nonexistent.csv")

    def test_csv_wrong_extension(self, tmp_path):
        path = os.path.join(str(tmp_path), "test.txt")
        with open(path, "w") as f:
            f.write("hello")
        with pytest.raises(ValueError, match="Expected a .csv"):
            read_csv(path)

    def test_csv_multiple_columns(self, tmp_path):
        path = self._create_csv(
            [
                ["ID", "Name", "Profile Link", "Email"],
                ["1", "John", "https://www.linkedin.com/in/johndoe", "j@test.com"],
                ["2", "Jane", "https://www.linkedin.com/in/janedoe", "ja@test.com"],
            ],
            str(tmp_path),
        )
        results = read_csv(path)
        assert len(results) == 2
        assert results[0]["url"] == "https://www.linkedin.com/in/johndoe"

    def test_csv_with_whitespace_urls(self, tmp_path):
        path = self._create_csv(
            [
                ["URL"],
                ["  https://www.linkedin.com/in/johndoe  "],
                ["https://www.linkedin.com/in/janedoe/"],
            ],
            str(tmp_path),
        )
        results = read_csv(path)
        assert len(results) == 2
        assert results[0]["url"] == "https://www.linkedin.com/in/johndoe"
        assert results[1]["url"] == "https://www.linkedin.com/in/janedoe"


# ─── XLSX Reader Tests ───────────────────────────────────────────────────────


class TestReadXLSX:
    """Tests for Excel file reading."""

    def _create_xlsx(self, rows: list[list[str]], tmpdir: str) -> str:
        """Helper to create a temporary XLSX file."""
        from openpyxl import Workbook

        path = os.path.join(tmpdir, "test.xlsx")
        wb = Workbook()
        ws = wb.active
        for row in rows:
            ws.append(row)
        wb.save(path)
        return path

    def test_xlsx_with_header(self, tmp_path):
        path = self._create_xlsx(
            [
                ["Name", "LinkedIn URL", "Company"],
                ["John", "https://www.linkedin.com/in/johndoe", "Acme"],
                ["Jane", "https://www.linkedin.com/in/janedoe", "Beta"],
            ],
            str(tmp_path),
        )
        results = read_xlsx(path)
        assert len(results) == 2
        assert results[0]["url"] == "https://www.linkedin.com/in/johndoe"
        assert results[0]["row"] == 2

    def test_xlsx_without_header(self, tmp_path):
        path = self._create_xlsx(
            [
                ["https://www.linkedin.com/in/johndoe"],
                ["https://www.linkedin.com/in/janedoe"],
            ],
            str(tmp_path),
        )
        results = read_xlsx(path)
        assert len(results) == 2

    def test_xlsx_with_invalid_urls(self, tmp_path):
        path = self._create_xlsx(
            [
                ["LinkedIn URL"],
                ["https://www.linkedin.com/in/johndoe"],
                ["not-a-url"],
                ["https://www.linkedin.com/in/janedoe"],
            ],
            str(tmp_path),
        )
        results = read_xlsx(path)
        assert len(results) == 2

    def test_xlsx_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_xlsx("nonexistent.xlsx")

    def test_xlsx_multiple_columns(self, tmp_path):
        path = self._create_xlsx(
            [
                ["ID", "Name", "Profile URL", "Email"],
                ["1", "John", "https://www.linkedin.com/in/johndoe", "j@test.com"],
                ["2", "Jane", "https://www.linkedin.com/in/janedoe", "ja@test.com"],
            ],
            str(tmp_path),
        )
        results = read_xlsx(path)
        assert len(results) == 2
        assert results[0]["url"] == "https://www.linkedin.com/in/johndoe"


# ─── read_spreadsheet (auto-detect) Tests ────────────────────────────────────


class TestReadSpreadsheet:
    """Tests for the unified read_spreadsheet function."""

    def test_auto_detects_csv(self, tmp_path):
        path = os.path.join(str(tmp_path), "test.csv")
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerows([
                ["URL"],
                ["https://www.linkedin.com/in/johndoe"],
            ])
        results = read_spreadsheet(path)
        assert len(results) == 1

    def test_auto_detects_xlsx(self, tmp_path):
        from openpyxl import Workbook

        path = os.path.join(str(tmp_path), "test.xlsx")
        wb = Workbook()
        ws = wb.active
        ws.append(["URL"])
        ws.append(["https://www.linkedin.com/in/johndoe"])
        wb.save(path)

        results = read_spreadsheet(path)
        assert len(results) == 1

    def test_unsupported_format_raises(self, tmp_path):
        path = os.path.join(str(tmp_path), "test.json")
        with open(path, "w") as f:
            f.write("{}")
        with pytest.raises(ValueError, match="Unsupported file format"):
            read_spreadsheet(path)

    def test_google_sheets_url_detected(self):
        # We can't actually test Google Sheets without credentials,
        # but we can verify the URL detection logic
        from spreadsheet_reader import _is_google_sheets_url

        assert _is_google_sheets_url("https://docs.google.com/spreadsheets/d/abc123/edit")
        assert not _is_google_sheets_url("https://www.linkedin.com/in/johndoe")
        assert not _is_google_sheets_url("/path/to/file.csv")


# ─── Sample File Test ────────────────────────────────────────────────────────


class TestSampleFile:
    """Test reading the bundled sample CSV file."""

    def test_read_sample_urls_csv(self):
        sample_path = Path(__file__).resolve().parent / "sample_urls.csv"
        if not sample_path.exists():
            pytest.skip("sample_urls.csv not found")
        results = read_csv(str(sample_path))
        assert len(results) == 5
        assert all("linkedin.com/in/" in r["url"] for r in results)
