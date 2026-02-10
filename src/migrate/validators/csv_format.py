"""Layer 2: CSV Format Validator.

Validates that the redirect CSV is properly formatted for Shopify import.
Ported from validate_csv_format.py (413 lines) — configurable columns, limits.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class CSVFormatValidator:
    """Validates redirect CSV format for Shopify compatibility."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.rows: list[dict[str, str]] = []
        self.checks: list[dict] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _find_csv(self) -> Path:
        """Locate the redirect CSV in the output directory."""
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    def _check(self, name: str, passed: bool, details: str = "") -> bool:
        status = "PASS" if passed else "FAIL"
        self.checks.append({"name": name, "passed": passed, "status": status, "details": details})
        if not passed:
            self.errors.append(f"{name}: {details}")
        return passed

    # ── Validation checks ────────────────────────────────────

    def validate_file_exists(self) -> bool:
        if not self.csv_path.exists():
            return self._check("File exists", False, f"Not found: {self.csv_path}")
        return self._check("File exists", True, self.csv_path.name)

    def validate_columns(self) -> tuple[bool, str | None, str | None]:
        """Check CSV has valid column pair."""
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f), None)

        if not header:
            self._check("Correct columns", False, "No header row found")
            return False, None, None

        header = [col.strip() for col in header]
        valid_pairs = [
            ("Redirect from", "Redirect to"),
            ("old_url", "new_url"),
            ("source_url", "target_url"),
            ("from", "to"),
        ]

        for src, tgt in valid_pairs:
            if src in header and tgt in header:
                self._check("Correct columns", True, f"Found: '{src}', '{tgt}'")
                return True, src, tgt

        # Case-insensitive fallback
        header_lower = {h.lower(): h for h in header}
        for src, tgt in valid_pairs:
            if src.lower() in header_lower and tgt.lower() in header_lower:
                s, t = header_lower[src.lower()], header_lower[tgt.lower()]
                self._check("Correct columns", True, f"Found: '{s}', '{t}'")
                return True, s, t

        self._check("Correct columns", False, f"Invalid columns: {header}")
        return False, None, None

    def load_rows(self, source_col: str, target_col: str) -> None:
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            for i, row in enumerate(csv.DictReader(f), 2):
                self.rows.append(
                    {
                        "row_num": str(i),
                        "source": row.get(source_col, "").strip(),
                        "target": row.get(target_col, "").strip(),
                    }
                )

    def validate_no_blanks(self) -> bool:
        blanks = [r["row_num"] for r in self.rows if not r["source"] or not r["target"]]
        if blanks:
            return self._check("No blank rows", False, f"Blank in rows: {blanks[:10]}")
        return self._check("No blank rows", True, f"{len(self.rows)} rows, all populated")

    def validate_no_duplicates(self) -> bool:
        sources = [r["source"] for r in self.rows if r["source"]]
        dupes = {u: c for u, c in Counter(sources).items() if c > 1}
        if dupes:
            sample = list(dupes.items())[:5]
            detail = ", ".join(f"'{u}' ({c}x)" for u, c in sample)
            return self._check("No duplicate sources", False, f"Duplicates: {detail}")
        return self._check("No duplicate sources", True, f"All {len(sources)} unique")

    def validate_url_format(self) -> bool:
        src_issues = []
        tgt_issues = []
        for r in self.rows:
            if r["source"] and (r["source"].startswith("http") or not r["source"].startswith("/")):
                src_issues.append(r["row_num"])
            if r["target"] and not r["target"].startswith("/") and not r["target"].startswith("http"):
                tgt_issues.append(r["row_num"])

        ok = True
        if src_issues:
            ok = False
            self._check("Source URL format", False, f"{len(src_issues)} issues")
        else:
            self._check("Source URL format", True, "All relative paths")

        if tgt_issues:
            ok = False
            self._check("Target URL format", False, f"{len(tgt_issues)} issues")
        else:
            self._check("Target URL format", True, "All valid")

        return ok

    def validate_trailing_slashes(self) -> bool:
        with_slash = sum(1 for r in self.rows if r["source"].endswith("/") and r["source"] != "/")
        without = sum(1 for r in self.rows if r["source"] and not r["source"].endswith("/"))
        if with_slash and without:
            dominant = "with" if with_slash > without else "without"
            self.warnings.append(f"Inconsistent trailing slashes (mostly {dominant})")
        self._check("Consistent trailing slashes", True, f"{with_slash} with, {without} without")
        return True

    def validate_row_count(self) -> bool:
        limit = self.config.redirects.max_per_batch
        count = len(self.rows)
        if count > limit:
            return self._check("Within limits", False, f"{count} rows exceeds {limit}")
        if count == 0:
            return self._check("Within limits", False, "No rows found")
        return self._check("Within limits", True, f"{count} rows (max: {limit})")

    def validate_encoding(self) -> bool:
        issues = [r["row_num"] for r in self.rows if " " in r["source"] or any(ord(c) > 127 for c in r["source"])]
        if issues:
            return self._check("URL encoding", False, f"{len(issues)} URLs with encoding issues")
        return self._check("URL encoding", True, "All URLs properly formatted")

    # ── Runner ───────────────────────────────────────────────

    def run(self) -> bool:
        """Execute full validation. Returns True if all checks pass."""
        console.rule("[bold]Layer 2: CSV Format Validation")

        if not self.validate_file_exists():
            self._print_report()
            return False

        valid, src_col, tgt_col = self.validate_columns()
        if not valid or not src_col or not tgt_col:
            self._print_report()
            return False

        self.load_rows(src_col, tgt_col)
        self.validate_no_blanks()
        self.validate_no_duplicates()
        self.validate_url_format()
        self.validate_trailing_slashes()
        self.validate_row_count()
        self.validate_encoding()

        self._print_report()
        return all(c["passed"] for c in self.checks)

    def _print_report(self) -> None:
        for c in self.checks:
            icon = "[green]PASS[/green]" if c["passed"] else "[red]FAIL[/red]"
            console.print(f"  {icon} {c['name']}: {c['details']}")
        for w in self.warnings:
            console.print(f"  [yellow]WARN[/yellow] {w}")
