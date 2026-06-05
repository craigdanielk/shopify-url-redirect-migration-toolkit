"""Core migration engine — orchestrates fetchers + normalizer + matchers + output.

Replaces the 556-line monolith (complete_url_mapping.py).
No hardcoded domains or paths. Everything is config-driven.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress

from migrate.config import MigrationConfig
from migrate.fetchers.base import FetchResult
from migrate.matchers.exact import ExactMatcher
from migrate.matchers.fuzzy import FuzzyMatcher
from migrate.matchers.partial import PartialMatcher
from migrate.matchers.pattern import PatternMatcher
from migrate.matchers.pipeline import MatcherPipeline
from migrate.matchers.sku import SKUMatcher
from migrate.normalizer import apply_slug_transforms, extract_path, normalize_url

console = Console()


class MigrationEngine:
    """Orchestrates the full URL mapping pipeline."""

    def __init__(
        self,
        config: MigrationConfig,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.verbose = verbose
        self.output_dir = Path(config.output.directory)

        # Data stores
        self.source_data: FetchResult = FetchResult()
        self.target_data: FetchResult = FetchResult()

        # Lookup tables (built from target data)
        self.product_handles: dict[str, dict] = {}
        self.product_skus: dict[str, str] = {}
        self.product_titles: dict[str, str] = {}
        self.collection_handles: dict[str, dict] = {}
        self.collection_titles: dict[str, str] = {}
        self.page_handles: dict[str, dict] = {}

        # Source lookup tables
        self.magento_id_map: dict[str, dict] = {}
        self.magento_urlkey_map: dict[str, dict] = {}

        # Results
        self.all_mappings: list[dict[str, Any]] = []
        self.target_url_counts: dict[str, list[str]] = defaultdict(list)

    # ── Public API ───────────────────────────────────────────

    def fetch(self) -> None:
        """Fetch data from source and target platforms."""
        self.source_data = self._create_source_fetcher().fetch_all()
        self.target_data = self._create_target_fetcher().fetch_all()
        console.print("[green]Fetch complete.[/green]")

    def run(self) -> None:
        """Execute the full mapping pipeline."""
        console.rule("[bold]URL Migration Engine")

        # Load data
        self._load_data()

        # Build lookup tables
        self._build_target_lookups()
        self._build_source_lookups()

        # Build matcher pipeline
        pipeline = self._build_pipeline()
        console.print(f"  Matcher pipeline: {pipeline.matcher_names}")

        # Generate source URL inventory
        source_urls = self._build_source_url_inventory()
        console.print(f"  Source URLs to map: {len(source_urls)}")

        # Map each URL
        self._map_urls(source_urls, pipeline)

        # Detect loops
        loops = self._detect_loops()
        if loops:
            console.print(f"  [yellow]Warning: {len(loops)} redirect loops detected[/yellow]")

        # Write output
        if not self.dry_run:
            self._write_output()

        # Print summary
        self._print_summary()

    # ── Data Loading ─────────────────────────────────────────

    def _load_data(self) -> None:
        """Load source and target data from disk or fetch if not available."""
        source_dir = self.output_dir / "00_source_data" / "source"
        target_dir = self.output_dir / "00_source_data" / "target"

        # Try loading from disk first
        if source_dir.exists() and (source_dir / "products.json").exists():
            self.source_data = self._load_from_disk(source_dir)
            console.print(f"  Loaded source data from {source_dir}")
        elif self.source_data.products or self.source_data.raw_urls:
            console.print("  Using in-memory source data")
        else:
            console.print("  [yellow]No source data found. Run 'migrate fetch' first.[/yellow]")

        if target_dir.exists() and (target_dir / "products.json").exists():
            self.target_data = self._load_from_disk(target_dir)
            console.print(f"  Loaded target data from {target_dir}")
        elif self.target_data.products:
            console.print("  Using in-memory target data")
        else:
            console.print("  [yellow]No target data found. Run 'migrate fetch' first.[/yellow]")

    def _load_from_disk(self, directory: Path) -> FetchResult:
        """Load FetchResult from JSON files on disk."""
        result = FetchResult()
        for name, attr in [
            ("products.json", "products"),
            ("collections.json", "collections"),
            ("pages.json", "pages"),
            ("categories.json", "categories"),
            ("cms_pages.json", "pages"),
        ]:
            filepath = directory / name
            if filepath.exists():
                with open(filepath, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        current = getattr(result, attr)
                        if isinstance(current, list):
                            current.extend(data)
                        else:
                            setattr(result, attr, data)
                    else:
                        setattr(result, attr, data)
        return result

    # ── Lookup Table Construction ────────────────────────────

    def _build_target_lookups(self) -> None:
        """Build lookup tables from target (Shopify) data."""
        # Products
        for p in self.target_data.products:
            handle = (p.get("handle") or "").lower()
            title = (p.get("title") or "").lower()
            if handle:
                self.product_handles[handle] = {
                    "handle": p.get("handle"),
                    "title": p.get("title"),
                }
                if title:
                    self.product_titles[title] = p.get("handle")
            for var in p.get("variants", []):
                sku = (var.get("sku") or "").lower()
                if sku:
                    self.product_skus[sku] = p.get("handle")

        # Collections
        for c in self.target_data.collections:
            handle = (c.get("handle") or "").lower()
            title = (c.get("title") or "").lower()
            if handle:
                self.collection_handles[handle] = {
                    "handle": c.get("handle"),
                    "title": c.get("title"),
                }
                if title:
                    self.collection_titles[title] = c.get("handle")

        # Pages
        for p in self.target_data.pages:
            handle = (p.get("handle") or "").lower()
            if handle:
                self.page_handles[handle] = {
                    "handle": p.get("handle"),
                    "title": p.get("title"),
                }

        console.print(
            f"  Target lookups: {len(self.product_handles)} products, "
            f"{len(self.product_skus)} SKUs, "
            f"{len(self.collection_handles)} collections, "
            f"{len(self.page_handles)} pages"
        )

    def _build_source_lookups(self) -> None:
        """Build lookup tables from source (Magento) data."""
        for p in self.source_data.products:
            pid = str(p.get("id", ""))
            sku = (p.get("sku") or "").lower()
            name = p.get("name") or ""
            url_key = ""
            for attr in p.get("custom_attributes", []):
                if attr.get("attribute_code") == "url_key":
                    url_key = attr.get("value") or ""
                    break
            entry = {"id": pid, "sku": sku, "name": name, "url_key": url_key}
            if pid:
                self.magento_id_map[pid] = entry
            if url_key:
                self.magento_urlkey_map[url_key.lower()] = entry

        console.print(
            f"  Source lookups: {len(self.magento_id_map)} products by ID, "
            f"{len(self.magento_urlkey_map)} by url_key"
        )

    # ── Matcher Pipeline ─────────────────────────────────────

    def _build_pipeline(self) -> MatcherPipeline:
        """Build the matcher pipeline from config."""
        matcher_map: dict[str, Any] = {
            "exact": lambda: ExactMatcher(
                product_handles=self.product_handles,
                collection_handles=self.collection_handles,
                page_handles=self.page_handles,
                magento_urlkey_map=self.magento_id_map,
            ),
            "sku": lambda: SKUMatcher(
                sku_to_handle=self.product_skus,
                magento_urlkey_map=self.magento_urlkey_map,
                magento_id_map=self.magento_id_map,
            ),
            "fuzzy": lambda: FuzzyMatcher(
                title_to_handle=self.product_titles,
                collection_title_to_handle=self.collection_titles,
                threshold=self.config.matchers.fuzzy_threshold,
            ),
            "partial": lambda: PartialMatcher(
                product_handles=self.product_handles,
                collection_handles=self.collection_handles,
            ),
            "pattern": lambda: PatternMatcher(
                patterns=self.config.matchers.patterns,
            ),
        }

        matchers = []
        for name in self.config.matchers.pipeline:
            factory = matcher_map.get(name)
            if factory:
                matchers.append(factory())
            else:
                console.print(f"  [yellow]Unknown matcher: {name}[/yellow]")

        return MatcherPipeline(matchers)

    # ── Source URL Inventory ─────────────────────────────────

    def _build_source_url_inventory(self) -> list[dict[str, str]]:
        """Build the inventory of source URLs to map."""
        # If we have raw URLs (from CSV import), use those directly
        if self.source_data.raw_urls:
            return self.source_data.raw_urls

        urls: list[dict[str, str]] = []
        domains = self.config.source.domains or [""]
        slug_transforms = [
            {"from": t.from_, "to": t.to} for t in self.config.matchers.slug_transforms
        ]

        # Products
        for p in self.source_data.products:
            url_key = ""
            for attr in p.get("custom_attributes", []):
                if attr.get("attribute_code") == "url_key":
                    url_key = attr.get("value") or ""
                    break
            if url_key:
                for domain in domains:
                    prefix = f"https://{domain}" if domain else ""
                    urls.append(
                        {
                            "source_url": f"{prefix}/{url_key}.html",
                            "resource_type": "product",
                            "resource_id": str(p.get("id", "")),
                            "name": p.get("name", ""),
                            "url_key": url_key,
                        }
                    )

        # Categories
        if isinstance(self.source_data.categories, dict):
            cats = self._extract_categories(
                self.source_data.categories, slug_transforms=slug_transforms
            )
            for path, info in cats.items():
                if info.get("is_active", True):
                    for domain in domains:
                        prefix = f"https://{domain}" if domain else ""
                        urls.append(
                            {
                                "source_url": f"{prefix}/{path}.html",
                                "resource_type": "category",
                                "name": info.get("name", ""),
                                "url_key": info.get("slug", ""),
                            }
                        )

        # CMS Pages
        for p in self.source_data.pages:
            identifier = (p.get("identifier") or "").lower()
            if identifier and identifier not in ("home", "no-route", "enable-cookies"):
                for domain in domains:
                    prefix = f"https://{domain}" if domain else ""
                    urls.append(
                        {
                            "source_url": f"{prefix}/{identifier}",
                            "resource_type": "cms_page",
                            "name": p.get("title", ""),
                            "url_key": identifier,
                        }
                    )

        return urls

    def _extract_categories(
        self,
        node: dict,
        path: str = "",
        results: dict | None = None,
        slug_transforms: list[dict[str, str]] | None = None,
    ) -> dict[str, dict]:
        """Recursively extract category paths from Magento category tree."""
        if results is None:
            results = {}

        name = node.get("name", "")
        level = node.get("level", 0)
        is_active = node.get("is_active", False)

        slug = name.lower().replace(" ", "-").replace("/", "-")
        if slug_transforms:
            slug = apply_slug_transforms(slug, slug_transforms)
        slug = slug.encode("ascii", "ignore").decode("ascii")

        if level > 1:
            new_path = f"{path}/{slug}" if path else slug
            results[new_path] = {"name": name, "slug": slug, "is_active": is_active}
            if slug not in results:
                results[slug] = {"name": name, "slug": slug, "is_active": is_active}
        else:
            new_path = ""

        for child in node.get("children_data", []):
            self._extract_categories(child, new_path, results, slug_transforms)

        return results

    # ── URL Mapping ──────────────────────────────────────────

    def _map_urls(
        self,
        source_urls: list[dict[str, str]],
        pipeline: MatcherPipeline,
    ) -> None:
        """Map each source URL through the matcher pipeline."""
        target_domain = self.config.target.domain
        if target_domain and not target_domain.startswith("http"):
            target_domain = f"https://{target_domain}"

        with Progress(console=console) as progress:
            task = progress.add_task("Mapping URLs...", total=len(source_urls))

            for entry in source_urls:
                source_url = entry.get("source_url", "")
                resource_type = entry.get("resource_type", "unknown")
                url_key = entry.get("url_key", "")
                name = entry.get("name", "")
                resource_id = entry.get("resource_id", "")

                # Normalize the path
                path = extract_path(source_url)
                path = normalize_url(path, self.config.normalizer)

                # Infer cms_page when path matches page_mappings (e.g. Wayback gives "unknown")
                path_segment = (path.strip("/").split("/")[0] or "").split(".")[0]
                identifier_for_page = (url_key or path_segment).split(".")[0]
                if resource_type == "unknown" and identifier_for_page in self.config.page_mappings:
                    resource_type = "cms_page"
                    url_key = identifier_for_page

                mapping: dict[str, Any] = {
                    "source_url": source_url,
                    "target_url": "",
                    "resource_type": resource_type,
                    "mapping_status": "UNMAPPED",
                    "match_type": "none",
                    "confidence": 0.0,
                    "notes": "",
                }

                # Map the resource type
                if resource_type in ("product", "category", "collection"):
                    matcher_type = "collection" if resource_type == "category" else resource_type
                    result = pipeline.match(
                        url_key or path,
                        product_id=resource_id,
                        name=name,
                        resource_type=matcher_type,
                    )
                    if result:
                        target_path = result.target_path
                        if target_domain and target_path:
                            mapping["target_url"] = f"{target_domain}{target_path}"
                        else:
                            mapping["target_url"] = target_path
                        mapping["mapping_status"] = "MAPPED"
                        mapping["match_type"] = result.match_type
                        mapping["confidence"] = result.confidence
                    else:
                        mapping["mapping_status"] = f"UNMAPPED_{resource_type.upper()}"
                        mapping["notes"] = f"No matching Shopify {resource_type} found"

                elif resource_type == "cms_page":
                    identifier = url_key or path.replace(".html", "").strip("/")
                    # Check explicit page mappings from config
                    if identifier in self.config.page_mappings:
                        target_path = self.config.page_mappings[identifier]
                        mapping["target_url"] = (
                            f"{target_domain}{target_path}" if target_domain else target_path
                        )
                        mapping["mapping_status"] = "MAPPED"
                        mapping["match_type"] = "config_page_mapping"
                        mapping["confidence"] = 1.0
                    # Try matcher pipeline for pages
                    elif identifier.lower() in self.page_handles:
                        handle = self.page_handles[identifier.lower()]["handle"]
                        target_path = f"/pages/{handle}"
                        mapping["target_url"] = (
                            f"{target_domain}{target_path}" if target_domain else target_path
                        )
                        mapping["mapping_status"] = "MAPPED"
                        mapping["match_type"] = "exact"
                        mapping["confidence"] = 0.9
                    else:
                        mapping["mapping_status"] = "UNMAPPED_PAGE"
                        mapping["notes"] = "CMS page - needs manual verification"

                else:
                    # Try pattern matcher as fallback for unknown types
                    result = pipeline.match(url_key or path)
                    if result and result.target_path:
                        mapping["target_url"] = (
                            f"{target_domain}{result.target_path}"
                            if target_domain
                            else result.target_path
                        )
                        mapping["mapping_status"] = "MAPPED"
                        mapping["match_type"] = result.match_type
                        mapping["confidence"] = result.confidence
                    else:
                        mapping["mapping_status"] = "UNMAPPED"
                        mapping["notes"] = "Unknown resource type"

                self.all_mappings.append(mapping)
                if mapping["target_url"]:
                    self.target_url_counts[mapping["target_url"]].append(source_url)

                progress.update(task, advance=1)

    # ── Loop Detection ───────────────────────────────────────

    def _detect_loops(self) -> list[tuple[str, str]]:
        """Pre-upload loop detection: find A->B->C chains and A->B->A loops."""
        redirect_graph: dict[str, str] = {}
        for m in self.all_mappings:
            if m["mapping_status"] == "MAPPED" and m["target_url"]:
                source_path = extract_path(m["source_url"])
                target_path = extract_path(m["target_url"])
                redirect_graph[source_path] = target_path

        loops: list[tuple[str, str]] = []
        for source, target in redirect_graph.items():
            visited = {source}
            current = target
            depth = 0
            while current in redirect_graph and depth < 20:
                if current in visited:
                    loops.append((source, current))
                    break
                visited.add(current)
                current = redirect_graph[current]
                depth += 1

        return loops

    # ── Output ───────────────────────────────────────────────

    def _write_output(self) -> None:
        """Write all output files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        mapping_dir = self.output_dir / "04_redirect_mapping"
        output_dir = self.output_dir / "06_output"
        rules_dir = self.output_dir / "03_mapping_rules"

        mapping_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        rules_dir.mkdir(parents=True, exist_ok=True)

        # 1. Complete mapping CSV
        with open(mapping_dir / "complete_mapping.csv", "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "source_url",
                "target_url",
                "resource_type",
                "mapping_status",
                "match_type",
                "confidence",
                "notes",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.all_mappings)

        # 2. Shopify redirects CSV (mapped only, deduplicated)
        src_col = self.config.output.csv_columns.get("source", "Redirect from")
        tgt_col = self.config.output.csv_columns.get("target", "Redirect to")
        target_domain = self.config.target.domain
        if target_domain and not target_domain.startswith("http"):
            target_domain = f"https://{target_domain}"

        redirects: list[dict[str, str]] = []
        seen_sources: set[str] = set()

        for m in self.all_mappings:
            if m["mapping_status"] in ("MAPPED", "FALLBACK_TO_PARENT") and m["target_url"]:
                source_path = extract_path(m["source_url"])
                target_path = extract_path(m["target_url"])
                if source_path and source_path not in seen_sources:
                    redirects.append({src_col: source_path, tgt_col: target_path})
                    seen_sources.add(source_path)

        # Apply market locale prefixes if configured
        redirects = self._apply_market_prefixes(redirects)

        with open(
            output_dir / "shopify_redirects_complete.csv", "w", newline="", encoding="utf-8"
        ) as f:
            writer = csv.DictWriter(f, fieldnames=[src_col, tgt_col])
            writer.writeheader()
            writer.writerows(redirects)

        # 3. Unmapped URLs
        unmapped = [m for m in self.all_mappings if m["mapping_status"].startswith("UNMAPPED")]
        with open(rules_dir / "unmapped_urls.csv", "w", newline="", encoding="utf-8") as f:
            fieldnames = [
                "source_url",
                "resource_type",
                "mapping_status",
                "notes",
                "suggested_action",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for m in unmapped:
                writer.writerow(
                    {
                        "source_url": m["source_url"],
                        "resource_type": m["resource_type"],
                        "mapping_status": m["mapping_status"],
                        "notes": m["notes"],
                        "suggested_action": "MANUAL_REVIEW",
                    }
                )

        # 4. Duplicates log
        duplicates = [(t, srcs) for t, srcs in self.target_url_counts.items() if len(srcs) > 1]
        with open(mapping_dir / "duplicates_log.csv", "w", newline="", encoding="utf-8") as f:
            fieldnames = ["target_url", "source_url_count", "source_urls"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for target, sources in duplicates:
                writer.writerow(
                    {
                        "target_url": target,
                        "source_url_count": len(sources),
                        "source_urls": " | ".join(sources[:5])
                        + ("..." if len(sources) > 5 else ""),
                    }
                )

        console.print(f"\n[green]Output written to {self.output_dir}/[/green]")
        console.print(f"  Redirects: {len(redirects)}")
        console.print(f"  Unmapped: {len(unmapped)}")
        console.print(f"  Duplicates: {len(duplicates)}")

    # ── Summary ──────────────────────────────────────────────

    def _print_summary(self) -> None:
        """Print mapping summary."""
        status_counts: dict[str, int] = defaultdict(int)
        match_type_counts: dict[str, int] = defaultdict(int)

        for m in self.all_mappings:
            status_counts[m["mapping_status"]] += 1
            if m["match_type"] and m["match_type"] != "none":
                match_type_counts[m["match_type"]] += 1

        console.rule("[bold]Mapping Summary")
        console.print(f"Total source URLs: {len(self.all_mappings)}")
        console.print()
        console.print("[bold]Status breakdown:[/bold]")
        for status, count in sorted(status_counts.items()):
            color = "green" if status == "MAPPED" else "yellow" if "FALLBACK" in status else "red"
            console.print(f"  [{color}]{status}[/{color}]: {count}")

        console.print()
        console.print("[bold]Match type breakdown:[/bold]")
        for mtype, count in sorted(match_type_counts.items(), key=lambda x: -x[1]):
            console.print(f"  {mtype}: {count}")

    # ── Multi-Market Support ─────────────────────────────────

    def _apply_market_prefixes(self, redirects: list[dict[str, str]]) -> list[dict[str, str]]:
        """Duplicate redirects for each configured market with locale prefixes."""
        markets = self.config.markets
        if not markets:
            return redirects

        src_col = self.config.output.csv_columns.get("source", "Redirect from")
        tgt_col = self.config.output.csv_columns.get("target", "Redirect to")
        expanded: list[dict[str, str]] = []

        for r in redirects:
            # Keep the original (no-prefix) redirect
            expanded.append(r)
            # Add market-prefixed variants
            for market in markets:
                prefix = market.prefix
                if prefix:
                    expanded.append(
                        {
                            src_col: f"{prefix}{r[src_col]}",
                            tgt_col: f"{prefix}{r[tgt_col]}",
                        }
                    )

        if len(expanded) > len(redirects):
            console.print(
                f"  Multi-market: expanded {len(redirects)} → {len(expanded)} "
                f"redirects ({len(markets)} locales)"
            )

        return expanded

    # ── Fetcher Factory ──────────────────────────────────────

    def _create_source_fetcher(self):
        """Create the appropriate source fetcher based on config."""
        platform = self.config.source.platform

        if platform == "magento":
            from migrate.fetchers.magento import MagentoFetcher

            api = self.config.source.api
            return MagentoFetcher(
                base_url=api.base_url,
                consumer_key=api.consumer_key,
                consumer_secret=api.consumer_secret,
                access_token=api.access_token,
                access_token_secret=api.access_token_secret,
                output_dir=self.output_dir / "00_source_data" / "source",
            )

        elif platform == "csv":
            from migrate.fetchers.csv_import import CSVImportFetcher

            cols = self.config.source.csv_columns
            return CSVImportFetcher(
                csv_path=self.config.source.csv_file,
                url_column=cols.get("url", "source_url"),
                type_column=cols.get("type", "resource_type"),
                name_column=cols.get("name", "name"),
            )

        elif platform == "wordpress":
            from migrate.fetchers.wordpress import WordPressFetcher

            return WordPressFetcher(
                base_url=self.config.source.api.base_url,
                output_dir=self.output_dir / "00_source_data" / "source",
            )

        elif platform == "sitemap":
            from migrate.fetchers.sitemap import SitemapFetcher

            return SitemapFetcher(
                sitemap_url=self.config.discover.sitemap_url
                or f"{self.config.source.api.base_url}/sitemap.xml",
                output_dir=self.output_dir / "00_source_data" / "source",
            )

        elif platform == "wayback":
            from migrate.fetchers.wayback import WaybackFetcher

            return WaybackFetcher(
                domains=self.config.source.domains,
                output_dir=self.output_dir / "00_source_data" / "source",
            )

        else:
            raise ValueError(f"Unsupported source platform: {platform}")

    def _create_target_fetcher(self):
        """Create the appropriate target fetcher based on config."""
        platform = self.config.target.platform

        if platform == "shopify":
            from migrate.fetchers.shopify import ShopifyFetcher

            api = self.config.target.api
            return ShopifyFetcher(
                store_url=api.store_url,
                access_token=api.access_token,
                api_version=api.api_version,
                output_dir=self.output_dir / "00_source_data" / "target",
            )

        else:
            raise ValueError(f"Unsupported target platform: {platform}")
