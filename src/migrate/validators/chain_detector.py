"""Layer 3: Redirect Chain Detector.

Tests actual redirects AFTER Shopify import to verify they work.
Ported from validate_redirect_chains.py (393 lines) — store URL from config.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import requests
from rich.console import Console
from rich.progress import Progress

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class ChainDetectorValidator:
    """Tests live redirects after Shopify import."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.session = requests.Session()
        self.results: list[dict] = []
        self.pass_count = 0
        self.fail_count = 0

        # Build store URL
        store = config.target.api.store_url
        if not store.startswith("http"):
            store = f"https://{store}"
        self.store_url = store.rstrip("/")

    def _find_csv(self) -> Path:
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    def _normalize_url(self, url: str) -> str:
        if url.startswith("/"):
            url = urljoin(self.store_url, url)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/") or "/"
        return f"{parsed.scheme}://{parsed.netloc.lower()}{path}"

    def _load_mappings(self) -> list[dict[str, str]]:
        if not self.csv_path.exists():
            console.print(f"[red]CSV not found: {self.csv_path}[/red]")
            return []

        mappings: list[dict[str, str]] = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            src_col = tgt_col = None
            for s, t in [("Redirect from", "Redirect to"), ("old_url", "new_url")]:
                if s in fieldnames and t in fieldnames:
                    src_col, tgt_col = s, t
                    break
            if not src_col:
                return []
            for row in reader:
                source = row.get(src_col, "").strip()
                target = row.get(tgt_col, "").strip()
                if source and target:
                    mappings.append({"source": source, "expected_target": target})

        return mappings

    def _test_redirect(self, source: str, expected: str) -> dict:
        max_depth = self.config.validation.max_chain_depth
        timeout = self.config.validation.request_timeout
        full_source = urljoin(self.store_url, source)

        result = {
            "source_url": source,
            "expected_target": expected,
            "status_code": "",
            "redirect_count": 0,
            "final_url": "",
            "matches_target": False,
            "result": "UNKNOWN",
            "error": "",
        }

        try:
            resp = self.session.get(full_source, allow_redirects=False, timeout=timeout)
            result["status_code"] = resp.status_code
            current_url = full_source
            count = 0

            while resp.is_redirect and count < max_depth:
                count += 1
                location = resp.headers.get("Location", "")
                if not location:
                    break
                current_url = urljoin(current_url, location)
                resp = self.session.get(current_url, allow_redirects=False, timeout=timeout)

            result["redirect_count"] = count
            result["final_url"] = current_url

            if count >= max_depth:
                result["result"] = "FAIL"
                result["error"] = "Redirect loop detected"
            elif not resp.is_redirect and resp.status_code == 404:
                result["result"] = "FAIL"
                result["error"] = "404 - Not found"
            else:
                norm_final = self._normalize_url(current_url)
                norm_expected = self._normalize_url(expected)
                if norm_final == norm_expected or urlparse(norm_final).path == urlparse(norm_expected).path:
                    result["matches_target"] = True
                    result["result"] = "PASS"
                else:
                    result["result"] = "FAIL"
                    result["error"] = f"Mismatch: got {current_url}"

        except requests.Timeout:
            result["result"] = "FAIL"
            result["error"] = "Timeout"
        except requests.RequestException as e:
            result["result"] = "FAIL"
            result["error"] = str(e)[:80]

        return result

    def run(self) -> bool:
        """Execute live redirect testing. Returns True if all pass."""
        console.rule("[bold]Layer 3: Live Redirect Chain Validation")
        console.print(f"Testing against: {self.store_url}")

        mappings = self._load_mappings()
        if not mappings:
            console.print("[yellow]No mappings to test.[/yellow]")
            return True

        delay = self.config.validation.rate_limit_delay

        with Progress(console=console) as progress:
            task = progress.add_task("Testing redirects...", total=len(mappings))
            for m in mappings:
                result = self._test_redirect(m["source"], m["expected_target"])
                self.results.append(result)
                if result["result"] == "PASS":
                    self.pass_count += 1
                else:
                    self.fail_count += 1
                progress.update(task, advance=1)
                time.sleep(delay)

        total = self.pass_count + self.fail_count
        rate = (self.pass_count / total * 100) if total else 0
        console.print(f"  Pass: {self.pass_count}, Fail: {self.fail_count}, Rate: {rate:.1f}%")

        if self.fail_count:
            console.print("[red]Failed redirects:[/red]")
            for r in self.results[:10]:
                if r["result"] != "PASS":
                    console.print(f"  {r['source_url']} -> {r['error']}")

        return self.fail_count == 0
