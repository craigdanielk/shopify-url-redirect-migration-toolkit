"""Wayback Machine CDX API fetcher — discovers historical URLs.

Queries the Internet Archive's CDX API to find all archived URLs for configured
domains, deduplicates them, and classifies by CMS era.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()

# CMS era classification patterns
ERA_PATTERNS: list[tuple[str, list[str]]] = [
    ("typo3", [".html", "index.php?id=", "typo3/"]),
    ("wordpress", ["/wp-content/", "/wp-admin/", "/wp-json/", "/?p=", "/?page_id="]),
    ("drupal", ["/node/", "/sites/default/", "/modules/", "/drupal/"]),
    ("wix", ["/_wix", "#!", "/wix/"]),
    ("magento", ["/catalog/", "/catalogsearch/", "/customer/", "/checkout/", "/rest/V1/"]),
    ("shopify", ["/products/", "/collections/", "/pages/", "/blogs/", "/cart", "/admin/"]),
]

# MIME types to exclude (non-page resources)
EXCLUDE_MIME_PREFIXES = [
    "image/",
    "text/css",
    "application/javascript",
    "application/json",
    "font/",
    "video/",
    "audio/",
    "application/octet-stream",
]


class WaybackFetcher:
    """Discovers historical URLs via the Wayback Machine CDX API."""

    def __init__(
        self,
        domains: list[str],
        output_dir: str | Path | None = None,
        exclude_status: list[int] | None = None,
        exclude_mime: list[str] | None = None,
        collapse: str = "urlkey",
    ) -> None:
        self.domains = domains
        self.output_dir = Path(output_dir) if output_dir else None
        self.exclude_status = set(exclude_status or [404, 500, 503])
        self.exclude_mime = exclude_mime or EXCLUDE_MIME_PREFIXES
        self.collapse = collapse
        self.session = requests.Session()

    def _query_cdx(self, domain: str) -> list[dict[str, str]]:
        """Query the CDX API for a single domain."""
        url = "https://web.archive.org/cdx/search/cdx"
        params = {
            "url": domain,
            "matchType": "prefix",
            "output": "json",
            "fl": "original,timestamp,statuscode,mimetype",
            "collapse": self.collapse,
            "limit": "50000",
        }

        results: list[dict[str, str]] = []
        try:
            console.print(f"  Querying CDX for {domain}...")
            response = self.session.get(url, params=params, timeout=60)

            if response.status_code == 429:
                console.print("  [yellow]Rate limited, waiting 10s...[/yellow]")
                time.sleep(10)
                return self._query_cdx(domain)

            if response.status_code != 200:
                console.print(f"  [red]CDX API error: {response.status_code}[/red]")
                return []

            data = response.json()
            if not data or len(data) < 2:
                return []

            # First row is headers, rest is data
            headers = data[0]
            for row in data[1:]:
                entry = dict(zip(headers, row))
                results.append(entry)

        except requests.RequestException as e:
            console.print(f"  [red]CDX request failed: {e}[/red]")
        except ValueError:
            console.print("  [red]CDX response was not valid JSON[/red]")

        return results

    def _filter_entries(self, entries: list[dict[str, str]]) -> list[dict[str, str]]:
        """Filter out non-page resources and error status codes."""
        filtered = []
        for entry in entries:
            status = entry.get("statuscode", "")
            mime = entry.get("mimetype", "")

            # Skip error status codes
            if status.isdigit() and int(status) in self.exclude_status:
                continue

            # Skip non-page MIME types
            if any(mime.startswith(prefix) for prefix in self.exclude_mime):
                continue

            filtered.append(entry)

        return filtered

    def _deduplicate(self, entries: list[dict[str, str]]) -> list[dict[str, str]]:
        """Deduplicate by normalized path."""
        seen: dict[str, dict[str, str]] = {}
        for entry in entries:
            original = entry.get("original", "")
            parsed = urlparse(original)
            # Normalize: lowercase path, strip trailing slash, strip query for dedup
            path = parsed.path.lower().rstrip("/") or "/"
            if path not in seen:
                seen[path] = entry

        return list(seen.values())

    @staticmethod
    def classify_era(url: str) -> str:
        """Classify a URL into its CMS era based on patterns."""
        url_lower = url.lower()
        for era, patterns in ERA_PATTERNS:
            if any(p in url_lower for p in patterns):
                return era
        return "unknown"

    def _build_url_entries(self, entries: list[dict[str, str]]) -> list[dict[str, str]]:
        """Convert CDX entries to standardized URL entries."""
        url_entries: list[dict[str, str]] = []
        for entry in entries:
            original = entry.get("original", "")
            parsed = urlparse(original)
            path = parsed.path

            # Skip root-only paths
            if not path or path == "/":
                continue

            era = self.classify_era(original)

            url_entries.append(
                {
                    "source_url": original,
                    "path": path,
                    "resource_type": "unknown",
                    "name": "",
                    "url_key": path.strip("/").split("/")[-1] if path.strip("/") else "",
                    "era": era,
                    "domain": parsed.netloc,
                    "timestamp": entry.get("timestamp", ""),
                }
            )

        return url_entries

    # ── Public API ───────────────────────────────────────────

    def fetch_products(self) -> list[dict[str, Any]]:
        return []

    def fetch_collections(self) -> list[dict[str, Any]]:
        return []

    def fetch_pages(self) -> list[dict[str, Any]]:
        return []

    def fetch_all(self) -> FetchResult:
        """Discover all historical URLs across configured domains."""
        console.print("[bold]Discovering historical URLs via Wayback Machine...[/bold]")

        all_entries: list[dict[str, str]] = []

        for domain in self.domains:
            # Query with and without www
            for variant in [domain, f"www.{domain}"]:
                entries = self._query_cdx(variant)
                all_entries.extend(entries)
                time.sleep(1)  # Be polite to the CDX API

        console.print(f"  Raw entries: {len(all_entries)}")

        # Filter
        filtered = self._filter_entries(all_entries)
        console.print(f"  After filtering: {len(filtered)}")

        # Deduplicate
        deduped = self._deduplicate(filtered)
        console.print(f"  After deduplication: {len(deduped)}")

        # Build structured entries
        url_entries = self._build_url_entries(deduped)

        # Classify eras
        era_counts: dict[str, int] = {}
        for entry in url_entries:
            era = entry.get("era", "unknown")
            era_counts[era] = era_counts.get(era, 0) + 1

        console.print("  [bold]CMS era breakdown:[/bold]")
        for era, count in sorted(era_counts.items(), key=lambda x: -x[1]):
            console.print(f"    {era}: {count}")

        # Save to disk
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            csv_path = self.output_dir / "wayback_urls.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "source_url",
                        "path",
                        "resource_type",
                        "name",
                        "url_key",
                        "era",
                        "domain",
                        "timestamp",
                    ],
                )
                writer.writeheader()
                writer.writerows(url_entries)
            console.print(f"  Saved to {csv_path}")

        console.print(f"[green]Discovered {len(url_entries)} unique historical URLs[/green]")

        return FetchResult(raw_urls=url_entries)
