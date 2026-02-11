"""Shopify redirect uploader — creates redirects via REST API.

Reads a validated redirect CSV and pushes each entry to the Shopify
Redirects API. Handles rate limiting, deduplication, chain flattening,
and rollback.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from rich.console import Console
from rich.progress import Progress

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class ShopifyUploader:
    """Creates redirects in Shopify via the REST Admin API."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config

        # API setup
        store_url = config.target.api.store_url.rstrip("/")
        if not store_url.startswith("http"):
            store_url = f"https://{store_url}"
        self.store_url = store_url
        self.api_version = config.target.api.api_version

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Shopify-Access-Token": config.target.api.access_token,
                "Content-Type": "application/json",
            }
        )

        # Upload config
        upload_cfg = getattr(config, "upload", None)
        self.batch_size = getattr(upload_cfg, "batch_size", 50) if upload_cfg else 50
        self.pause_between = getattr(upload_cfg, "pause_between_batches", 2) if upload_cfg else 2
        self.skip_existing = getattr(upload_cfg, "skip_existing", True) if upload_cfg else True
        self.flatten_chains = getattr(upload_cfg, "flatten_chains", True) if upload_cfg else True

        # CSV path
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()

        # Tracking
        self.created_ids: list[int] = []
        self.skipped: list[dict] = []
        self.errors: list[dict] = []

    @property
    def _api_base(self) -> str:
        return f"{self.store_url}/admin/api/{self.api_version}"

    def _find_csv(self) -> Path:
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    # ── Existing redirects ───────────────────────────────────

    def _fetch_existing_redirects(self) -> dict[str, dict]:
        """Fetch all existing redirects from Shopify. Returns {path: {id, target}}."""
        existing: dict[str, dict] = {}
        url: str | None = f"{self._api_base}/redirects.json?limit=250"

        while url:
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 429:
                    time.sleep(int(resp.headers.get("Retry-After", 2)))
                    continue
                resp.raise_for_status()
                data = resp.json()
                for r in data.get("redirects", []):
                    existing[r["path"]] = {"id": r["id"], "target": r["target"]}
            except requests.RequestException as e:
                console.print(f"  [red]Error fetching existing redirects: {e}[/red]")
                break

            # Pagination via Link header
            url = None
            link = resp.headers.get("Link", "")
            for part in link.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip("<> ")
                    break

        return existing

    # ── Chain flattening ─────────────────────────────────────

    def _flatten_chains(
        self, redirects: list[dict[str, str]], existing: dict[str, dict]
    ) -> list[dict[str, str]]:
        """Flatten redirect chains before upload.

        If new redirect A->B and existing B->C, change to A->C.
        """
        existing_map = {path: info["target"] for path, info in existing.items()}

        flattened_count = 0
        result: list[dict[str, str]] = []

        for r in redirects:
            source = r.get("source", "")
            target = r.get("target", "")

            # Follow chain in existing redirects
            final_target = target
            visited: set[str] = {source}
            depth = 0
            while final_target in existing_map and depth < 10:
                if final_target in visited:
                    break  # Cycle
                visited.add(final_target)
                final_target = existing_map[final_target]
                depth += 1

            if final_target != target:
                flattened_count += 1

            result.append({"source": source, "target": final_target})

        if flattened_count:
            console.print(f"  [yellow]Flattened {flattened_count} redirect chains[/yellow]")

        return result

    # ── Upload ───────────────────────────────────────────────

    def _create_redirect(self, path: str, target: str) -> dict | None:
        """Create a single redirect via the API."""
        url = f"{self._api_base}/redirects.json"
        payload = {"redirect": {"path": path, "target": target}}

        try:
            resp = self.session.post(url, json=payload, timeout=30)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2))
                time.sleep(retry_after)
                return self._create_redirect(path, target)

            if resp.status_code in (200, 201):
                data = resp.json().get("redirect", {})
                return data

            # Handle "path already taken"
            errors = resp.json().get("errors", {})
            if "path" in errors and "has already been taken" in str(errors["path"]):
                self.skipped.append({"path": path, "target": target, "reason": "already exists"})
                return None

            self.errors.append({"path": path, "target": target, "error": resp.text[:200]})
            return None

        except requests.RequestException as e:
            self.errors.append({"path": path, "target": target, "error": str(e)[:200]})
            return None

    def _load_redirects_from_csv(self) -> list[dict[str, str]]:
        """Load redirect pairs from the CSV."""
        if not self.csv_path.exists():
            console.print(f"[red]CSV not found: {self.csv_path}[/red]")
            return []

        redirects: list[dict[str, str]] = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            src_col = tgt_col = None
            for s, t in [
                ("Redirect from", "Redirect to"),
                ("old_url", "new_url"),
                ("source_url", "target_url"),
            ]:
                if s in fieldnames and t in fieldnames:
                    src_col, tgt_col = s, t
                    break

            if not src_col or not tgt_col:
                console.print(f"[red]Cannot detect columns in CSV: {fieldnames}[/red]")
                return []

            for row in reader:
                source = row.get(src_col, "").strip()
                target = row.get(tgt_col, "").strip()
                if source and target:
                    redirects.append({"source": source, "target": target})

        return redirects

    # ── Public API ───────────────────────────────────────────

    def upload(self, dry_run: bool = False) -> bool:
        """Upload redirects to Shopify. Returns True if all succeeded."""
        console.rule("[bold]Shopify Redirect Upload")
        console.print(f"Store: {self.store_url}")
        console.print(f"CSV: {self.csv_path}")

        redirects = self._load_redirects_from_csv()
        if not redirects:
            console.print("[yellow]No redirects to upload.[/yellow]")
            return True

        console.print(f"Redirects to process: {len(redirects)}")

        # Fetch existing for chain flattening and skip-existing
        existing: dict[str, dict] = {}
        if self.flatten_chains or self.skip_existing:
            console.print("Fetching existing redirects...")
            existing = self._fetch_existing_redirects()
            console.print(f"  Found {len(existing)} existing redirects")

        # Flatten chains
        if self.flatten_chains and existing:
            redirects = self._flatten_chains(redirects, existing)

        # Filter out already-existing
        if self.skip_existing:
            before = len(redirects)
            redirects = [r for r in redirects if r["source"] not in existing]
            skipped = before - len(redirects)
            if skipped:
                console.print(f"  Skipping {skipped} already-existing redirects")

        if not redirects:
            console.print("[green]All redirects already exist. Nothing to upload.[/green]")
            return True

        if dry_run:
            console.print(f"\n[yellow]DRY RUN: Would create {len(redirects)} redirects[/yellow]")
            for r in redirects[:10]:
                console.print(f"  {r['source']} -> {r['target']}")
            if len(redirects) > 10:
                console.print(f"  ... and {len(redirects) - 10} more")
            return True

        # Upload
        console.print(f"\nCreating {len(redirects)} redirects...")
        with Progress(console=console) as progress:
            task = progress.add_task("Uploading...", total=len(redirects))
            for i, r in enumerate(redirects):
                result = self._create_redirect(r["source"], r["target"])
                if result:
                    self.created_ids.append(result.get("id", 0))
                progress.update(task, advance=1)

                # Batch pause
                if (i + 1) % self.batch_size == 0:
                    time.sleep(self.pause_between)

        # Save manifest
        self._save_manifest()

        # Summary
        console.print(f"\n[green]Created: {len(self.created_ids)}[/green]")
        if self.skipped:
            console.print(f"[yellow]Skipped (existing): {len(self.skipped)}[/yellow]")
        if self.errors:
            console.print(f"[red]Errors: {len(self.errors)}[/red]")
            for e in self.errors[:5]:
                console.print(f"  {e['path']}: {e['error']}")

        return len(self.errors) == 0

    def rollback(self) -> bool:
        """Delete all redirects from the last upload using saved manifest."""
        manifest_path = Path(self.config.output.directory) / "upload_manifest.json"
        if not manifest_path.exists():
            console.print("[red]No upload manifest found. Cannot rollback.[/red]")
            return False

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        ids = manifest.get("created_ids", [])
        if not ids:
            console.print("[yellow]Manifest has no redirect IDs to delete.[/yellow]")
            return True

        console.print(f"Rolling back {len(ids)} redirects...")
        deleted = 0
        with Progress(console=console) as progress:
            task = progress.add_task("Deleting...", total=len(ids))
            for rid in ids:
                try:
                    url = f"{self._api_base}/redirects/{rid}.json"
                    resp = self.session.delete(url, timeout=30)
                    if resp.status_code == 429:
                        time.sleep(int(resp.headers.get("Retry-After", 2)))
                        resp = self.session.delete(url, timeout=30)
                    if resp.status_code in (200, 204):
                        deleted += 1
                except requests.RequestException:
                    pass
                progress.update(task, advance=1)
                time.sleep(0.2)

        console.print(f"[green]Deleted {deleted}/{len(ids)} redirects[/green]")
        return True

    def _save_manifest(self) -> None:
        """Save upload manifest for rollback support."""
        output_dir = Path(self.config.output.directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "timestamp": datetime.now().isoformat(),
            "store": self.store_url,
            "csv_path": str(self.csv_path),
            "created_ids": self.created_ids,
            "skipped_count": len(self.skipped),
            "error_count": len(self.errors),
        }
        with open(output_dir / "upload_manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
