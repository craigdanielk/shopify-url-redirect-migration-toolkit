"""Layer 4: Local Testing Helper.

Generates instructions and sample URLs for manual testing using hosts file override.
Ported from test_local_redirects.py (447 lines) — domains from config.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class LocalTesterValidator:
    """Generates local testing instructions and sample URLs."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.old_domains = config.validation.old_domains or []

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

    def _load_and_categorize(self) -> dict[str, list[dict]]:
        """Load redirects and categorize by target resource type."""
        categorized: dict[str, list[dict]] = defaultdict(list)
        if not self.csv_path.exists():
            return categorized

        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            src_col = tgt_col = None
            for s, t in [("Redirect from", "Redirect to"), ("old_url", "new_url")]:
                if s in fieldnames and t in fieldnames:
                    src_col, tgt_col = s, t
                    break
            if not src_col:
                return categorized
            for row in reader:
                source = row.get(src_col, "").strip()
                target = row.get(tgt_col, "").strip()
                if source and target:
                    cat = "other"
                    tl = target.lower()
                    if "/products/" in tl:
                        cat = "product"
                    elif "/collections/" in tl:
                        cat = "collection"
                    elif "/pages/" in tl:
                        cat = "page"
                    categorized[cat].append({"source": source, "target": target})

        return categorized

    def run(self) -> bool:
        """Generate local testing materials. Returns True always (advisory)."""
        console.rule("[bold]Layer 4: Local Testing Instructions")

        categorized = self._load_and_categorize()
        total = sum(len(v) for v in categorized.values())
        if not total:
            console.print("[yellow]No redirects to generate test instructions for.[/yellow]")
            return True

        # Select samples
        samples: list[dict] = []
        for cat in ["product", "collection", "page", "other"]:
            items = categorized.get(cat, [])
            if items:
                n = min(4, len(items))
                for item in random.sample(items, n):
                    item["category"] = cat
                    samples.append(item)

        output_dir = Path(self.config.output.directory) / "tests" / "pre-launch" / "validation_reports"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write instructions
        lines = [
            "=" * 70,
            "URL MIGRATION — Local Testing Instructions",
            "=" * 70,
            f"Target store: {self.store_url}",
            "",
            "STEP 1: Modify your hosts file to point old domains to Shopify IP.",
            "STEP 2: Verify hosts file is working (ping old domain).",
            "STEP 3: Test sample URLs below in an incognito browser.",
            "STEP 4: Clean up hosts file when done.",
            "",
            "-" * 70,
            "SAMPLE TEST URLs:",
            "-" * 70,
        ]
        for i, s in enumerate(samples, 1):
            domain = self.old_domains[i % len(self.old_domains)] if self.old_domains else "old-domain.example.com"
            full_source = f"https://{domain}{s['source']}"
            full_target = f"{self.store_url}{s['target']}" if s["target"].startswith("/") else s["target"]
            lines.extend([
                f"",
                f"  Test {i}: [{s['category'].upper()}]",
                f"  Source:   {full_source}",
                f"  Expected: {full_target}",
            ])
        lines.append("")
        lines.append("=" * 70)

        instructions_path = output_dir / "local_test_instructions.txt"
        instructions_path.write_text("\n".join(lines), encoding="utf-8")

        # Write checklist CSV
        checklist_path = output_dir / "manual_test_checklist.csv"
        with open(checklist_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Test #", "Category", "Source URL", "Expected Target", "Status", "Notes"])
            for i, s in enumerate(samples, 1):
                domain = self.old_domains[i % len(self.old_domains)] if self.old_domains else "example.com"
                writer.writerow([i, s["category"], f"https://{domain}{s['source']}", s["target"], "", ""])

        console.print(f"  Generated {len(samples)} test samples")
        console.print(f"  Instructions: {instructions_path}")
        console.print(f"  Checklist: {checklist_path}")
        return True
