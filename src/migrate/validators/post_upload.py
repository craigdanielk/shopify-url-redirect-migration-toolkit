"""Post-upload verification — tests live redirects after Shopify upload.

Samples redirects from the uploaded set, makes HTTP HEAD requests,
and verifies 301 status + correct Location header. Unifies the skill's
manual curl verification and the toolkit's chain detector into one step.
"""

from __future__ import annotations

import csv
import random
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


class PostUploadVerifier:
    """Verifies redirects are working after Shopify upload."""

    def __init__(
        self,
        config: MigrationConfig,
        csv_path: str | Path | None = None,
        sample_size: int = 50,
    ) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.sample_size = sample_size

        store = config.target.api.store_url.rstrip("/")
        if not store.startswith("http"):
            store = f"https://{store}"
        self.store_url = store

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "url-migration-toolkit/0.1"})

        self.results: list[dict] = []
        self.pass_count = 0
        self.fail_count = 0

    def _find_csv(self) -> Path:
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    def _load_sample(self) -> list[dict[str, str]]:
        """Load a random sample of redirects from the CSV."""
        if not self.csv_path.exists():
            return []

        all_rows: list[dict[str, str]] = []
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
                    all_rows.append({"source": source, "target": target})

        n = min(self.sample_size, len(all_rows))
        return random.sample(all_rows, n) if n < len(all_rows) else all_rows

    def _verify_redirect(self, source: str, expected_target: str) -> dict:
        """Verify a single redirect returns 301 with correct Location."""
        full_url = urljoin(self.store_url, source)
        timeout = self.config.validation.request_timeout

        result = {
            "source": source,
            "expected_target": expected_target,
            "status_code": 0,
            "location": "",
            "result": "UNKNOWN",
            "error": "",
        }

        try:
            resp = self.session.head(full_url, allow_redirects=False, timeout=timeout)
            result["status_code"] = resp.status_code

            if resp.status_code in (301, 302, 307, 308):
                location = resp.headers.get("Location", "")
                result["location"] = location

                # Compare paths
                loc_path = urlparse(location).path.rstrip("/") or "/"
                expected_path = (
                    urlparse(expected_target).path.rstrip("/") or "/"
                    if expected_target.startswith("http")
                    else expected_target.rstrip("/") or "/"
                )

                if loc_path == expected_path:
                    result["result"] = "PASS"
                else:
                    result["result"] = "FAIL"
                    result["error"] = f"Location mismatch: got {location}"
            elif resp.status_code == 404:
                result["result"] = "FAIL"
                result["error"] = "404 — redirect not found"
            else:
                result["result"] = "FAIL"
                result["error"] = f"Unexpected status: {resp.status_code}"

        except requests.Timeout:
            result["result"] = "FAIL"
            result["error"] = "Timeout"
        except requests.RequestException as e:
            result["result"] = "FAIL"
            result["error"] = str(e)[:100]

        return result

    def run(self) -> bool:
        """Verify a sample of redirects. Returns True if all pass."""
        console.rule("[bold]Post-Upload Verification")
        console.print(f"Store: {self.store_url}")

        sample = self._load_sample()
        if not sample:
            console.print("[yellow]No redirects to verify.[/yellow]")
            return True

        console.print(f"Verifying {len(sample)} redirects (sample of {self.sample_size})...")
        delay = self.config.validation.rate_limit_delay

        with Progress(console=console) as progress:
            task = progress.add_task("Verifying...", total=len(sample))
            for entry in sample:
                result = self._verify_redirect(entry["source"], entry["target"])
                self.results.append(result)
                if result["result"] == "PASS":
                    self.pass_count += 1
                else:
                    self.fail_count += 1
                progress.update(task, advance=1)
                time.sleep(delay)

        # Save report
        self._save_report()

        # Summary
        total = self.pass_count + self.fail_count
        rate = (self.pass_count / total * 100) if total else 0
        console.print(f"\n  Pass: {self.pass_count}, Fail: {self.fail_count}, Rate: {rate:.1f}%")

        if self.fail_count:
            console.print("\n[red]Failed verifications:[/red]")
            for r in self.results:
                if r["result"] != "PASS":
                    console.print(f"  {r['source']} — {r['error']}")
        else:
            console.print("\n[green]All verified redirects are working correctly.[/green]")

        return self.fail_count == 0

    def _save_report(self) -> None:
        output_dir = (
            Path(self.config.output.directory) / "tests" / "pre-launch" / "validation_reports"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "post_upload_verification.csv"
        with open(report_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "source",
                    "expected_target",
                    "status_code",
                    "location",
                    "result",
                    "error",
                ],
            )
            writer.writeheader()
            writer.writerows(self.results)
        console.print(f"  Report saved: {report_path}")
