"""Layer 1: Target Existence Validator.

Validates that all target URLs in the redirect CSV actually exist in Shopify.
Ported from validate_shopify_targets.py (398 lines) — uses ShopifyFetcher.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from rich.console import Console

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class TargetExistenceValidator:
    """Validates redirect targets exist in the Shopify store."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.products_cache: dict[str, dict] = {}
        self.collections_cache: dict[str, dict] = {}
        self.pages_cache: dict[str, dict] = {}
        self.results: list[dict] = []
        self.valid_count = 0
        self.broken_count = 0

    def _find_csv(self) -> Path:
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    def _load_shopify_resources(self) -> None:
        """Pre-load Shopify resources into cache via API."""
        from migrate.fetchers.shopify import ShopifyFetcher

        api = self.config.target.api
        fetcher = ShopifyFetcher(
            store_url=api.store_url,
            access_token=api.access_token,
            api_version=api.api_version,
        )

        data = fetcher.fetch_all()
        self.products_cache = {p["handle"]: p for p in data.products if p.get("handle")}
        self.collections_cache = {c["handle"]: c for c in data.collections if c.get("handle")}
        self.pages_cache = {p["handle"]: p for p in data.pages if p.get("handle")}

        total = len(self.products_cache) + len(self.collections_cache) + len(self.pages_cache)
        console.print(f"  Cached {total} Shopify resources")

    def _parse_target(self, target_url: str) -> tuple[str, str]:
        """Parse target URL to (resource_type, handle)."""
        path = urlparse(target_url).path if target_url.startswith("http") else target_url
        path = path.strip("/")
        parts = path.split("/")

        if len(parts) >= 2:
            rtype = parts[0].rstrip("s")
            handle = parts[1]
            if rtype in ("product", "collection", "page"):
                return rtype, handle

        return "unknown", parts[0] if parts else ""

    def _validate_target(self, target_url: str) -> dict:
        rtype, handle = self._parse_target(target_url)
        result = {
            "target_url": target_url,
            "resource_type": rtype,
            "handle": handle,
            "status": "UNKNOWN",
        }

        if rtype == "product":
            result["status"] = "VALID" if handle in self.products_cache else "BROKEN"
        elif rtype == "collection":
            result["status"] = "VALID" if handle in self.collections_cache else "BROKEN"
        elif rtype == "page":
            result["status"] = "VALID" if handle in self.pages_cache else "BROKEN"
        else:
            # Try all caches
            if handle in self.products_cache:
                result["status"] = "VALID"
                result["resource_type"] = "product"
            elif handle in self.collections_cache:
                result["status"] = "VALID"
                result["resource_type"] = "collection"
            elif handle in self.pages_cache:
                result["status"] = "VALID"
                result["resource_type"] = "page"
            else:
                result["status"] = "BROKEN"

        return result

    def _read_targets(self) -> list[str]:
        """Read unique target URLs from the redirect CSV."""
        if not self.csv_path.exists():
            console.print(f"[red]CSV not found: {self.csv_path}[/red]")
            return []

        targets: list[str] = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for col in ["Redirect to", "new_url", "target_url", "Target URL"]:
                if col in (reader.fieldnames or []):
                    f.seek(0)
                    next(csv.reader(f))  # skip header
                    reader = csv.DictReader(f)
                    for row in reader:
                        val = row.get(col, "").strip()
                        if val:
                            targets.append(val)
                    break

        return list(dict.fromkeys(targets))  # dedupe preserving order

    def run(self) -> bool:
        """Execute validation. Returns True if all targets are valid."""
        console.rule("[bold]Layer 1: Target Existence Validation")

        self._load_shopify_resources()
        targets = self._read_targets()
        if not targets:
            console.print("[yellow]No targets to validate.[/yellow]")
            return True

        for target in targets:
            result = self._validate_target(target)
            self.results.append(result)
            if result["status"] == "VALID":
                self.valid_count += 1
            else:
                self.broken_count += 1

        total = self.valid_count + self.broken_count
        rate = (self.valid_count / total * 100) if total else 0
        console.print(f"  Valid: {self.valid_count}, Broken: {self.broken_count}, Rate: {rate:.1f}%")

        if self.broken_count:
            console.print("[red]Broken targets:[/red]")
            for r in self.results:
                if r["status"] == "BROKEN":
                    console.print(f"  {r['target_url']} ({r['resource_type']}/{r['handle']})")

        return self.broken_count == 0
