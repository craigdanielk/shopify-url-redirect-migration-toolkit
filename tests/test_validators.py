"""Tests for the validation framework."""

import csv
from pathlib import Path

import pytest

from migrate.config import MigrationConfig
from migrate.validators.csv_format import CSVFormatValidator
from migrate.validators.loop_detector import LoopDetectorValidator


@pytest.fixture
def config():
    return MigrationConfig()


@pytest.fixture
def valid_csv(tmp_path):
    """Create a valid redirect CSV."""
    csv_path = tmp_path / "redirects.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Redirect from", "Redirect to"])
        writer.writerow(["/old-product", "/products/new-product"])
        writer.writerow(["/old-collection", "/collections/new-collection"])
        writer.writerow(["/old-page", "/pages/about"])
    return csv_path


@pytest.fixture
def csv_with_issues(tmp_path):
    """Create a CSV with various format issues."""
    csv_path = tmp_path / "bad_redirects.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Redirect from", "Redirect to"])
        writer.writerow(["/good", "/products/good"])
        writer.writerow(["", "/products/missing-source"])  # Blank source
        writer.writerow(["/dup", "/products/dup1"])
        writer.writerow(["/dup", "/products/dup2"])  # Duplicate source
        writer.writerow(["https://full-url.com/bad", "/products/x"])  # Full URL
    return csv_path


@pytest.fixture
def csv_with_loop(tmp_path):
    """Create a CSV with a redirect loop."""
    csv_path = tmp_path / "loop_redirects.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Redirect from", "Redirect to"])
        writer.writerow(["/a", "/b"])
        writer.writerow(["/b", "/c"])
        writer.writerow(["/c", "/a"])  # Loop: a -> b -> c -> a
        writer.writerow(["/safe", "/products/safe"])  # No loop
    return csv_path


# ── CSVFormatValidator ───────────────────────────────────────


class TestCSVFormatValidator:
    def test_valid_csv_passes(self, config, valid_csv):
        v = CSVFormatValidator(config, csv_path=valid_csv)
        assert v.run() is True

    def test_detects_missing_file(self, config, tmp_path):
        v = CSVFormatValidator(config, csv_path=tmp_path / "nonexistent.csv")
        assert v.run() is False

    def test_detects_blank_rows(self, config, csv_with_issues):
        v = CSVFormatValidator(config, csv_path=csv_with_issues)
        v.run()  # Will fail
        # Check that blank row check failed
        blank_check = next((c for c in v.checks if c["name"] == "No blank rows"), None)
        assert blank_check is not None
        assert blank_check["passed"] is False

    def test_detects_duplicates(self, config, csv_with_issues):
        v = CSVFormatValidator(config, csv_path=csv_with_issues)
        v.run()
        dup_check = next((c for c in v.checks if c["name"] == "No duplicate sources"), None)
        assert dup_check is not None
        assert dup_check["passed"] is False

    def test_detects_full_url_in_source(self, config, csv_with_issues):
        v = CSVFormatValidator(config, csv_path=csv_with_issues)
        v.run()
        fmt_check = next((c for c in v.checks if c["name"] == "Source URL format"), None)
        assert fmt_check is not None
        assert fmt_check["passed"] is False

    def test_empty_csv(self, config, tmp_path):
        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Redirect from", "Redirect to"])
        v = CSVFormatValidator(config, csv_path=csv_path)
        result = v.run()
        limit_check = next((c for c in v.checks if c["name"] == "Within limits"), None)
        assert limit_check is not None
        assert limit_check["passed"] is False

    def test_wrong_columns(self, config, tmp_path):
        csv_path = tmp_path / "wrong_cols.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["foo", "bar"])
            writer.writerow(["/a", "/b"])
        v = CSVFormatValidator(config, csv_path=csv_path)
        assert v.run() is False


# ── LoopDetectorValidator ────────────────────────────────────


class TestLoopDetector:
    def test_detects_simple_loop(self, config, csv_with_loop):
        v = LoopDetectorValidator(config, csv_path=csv_with_loop)
        result = v.run()
        assert result is False
        assert len(v.loops) > 0

    def test_no_loops_in_valid_csv(self, config, valid_csv):
        v = LoopDetectorValidator(config, csv_path=valid_csv)
        result = v.run()
        assert result is True
        assert len(v.loops) == 0

    def test_handles_missing_file(self, config, tmp_path):
        v = LoopDetectorValidator(config, csv_path=tmp_path / "nope.csv")
        result = v.run()
        assert result is True  # No data = no loops

    def test_detects_direct_loop(self, config, tmp_path):
        csv_path = tmp_path / "direct_loop.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Redirect from", "Redirect to"])
            writer.writerow(["/a", "/b"])
            writer.writerow(["/b", "/a"])
        v = LoopDetectorValidator(config, csv_path=csv_path)
        assert v.run() is False
        assert len(v.loops) > 0
