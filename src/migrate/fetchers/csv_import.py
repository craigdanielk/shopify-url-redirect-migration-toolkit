"""CSV import fetcher (NEW) — for clients without API access.

Loads source URLs from a plain CSV file rather than an API.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()


class CSVImportFetcher:
    """Loads URL data from a CSV file."""

    def __init__(
        self,
        csv_path: str | Path,
        url_column: str = "source_url",
        type_column: str = "resource_type",
        name_column: str = "name",
    ) -> None:
        self.csv_path = Path(csv_path)
        self.url_column = url_column
        self.type_column = type_column
        self.name_column = name_column

    def fetch_products(self) -> list[dict[str, Any]]:
        return []

    def fetch_collections(self) -> list[dict[str, Any]]:
        return []

    def fetch_pages(self) -> list[dict[str, Any]]:
        return []

    def fetch_all(self) -> FetchResult:
        """Read the CSV and return raw URL entries."""
        if not self.csv_path.exists():
            console.print(f"[red]CSV file not found: {self.csv_path}[/red]")
            return FetchResult()

        rows: list[dict[str, str]] = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(
                    {
                        "source_url": row.get(self.url_column, "").strip(),
                        "resource_type": row.get(self.type_column, "unknown").strip(),
                        "name": row.get(self.name_column, "").strip(),
                        "url_key": row.get("url_key", "").strip(),
                    }
                )

        console.print(f"  CSV: loaded {len(rows)} URL entries from {self.csv_path.name}")
        return FetchResult(raw_urls=rows)
