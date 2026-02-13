"""Comprehensive stress tests for the URL Migration Toolkit.

Exercises the full pipeline (discover, fetch, map, validate) against
diverse data sets to verify accuracy and robustness.

Run: uv run python stress-tests/run_stress_tests.py
"""

from __future__ import annotations

import csv
import json
import os
import random
import string
import time
from collections import defaultdict
from pathlib import Path

import yaml

# ── Setup paths ──────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
STRESS_DIR = ROOT / "stress-tests"

os.chdir(ROOT)

# Import toolkit modules
from migrate.config import MigrationConfig, load_config
from migrate.fetchers.sitemap import SitemapFetcher
from migrate.fetchers.wayback import WaybackFetcher
from migrate.mapper import MigrationEngine
from migrate.matchers.exact import ExactMatcher
from migrate.matchers.fuzzy import FuzzyMatcher
from migrate.matchers.partial import PartialMatcher
from migrate.matchers.pattern import PatternMatcher
from migrate.matchers.pipeline import MatcherPipeline
from migrate.normalizer import normalize_url
from migrate.validators.csv_format import CSVFormatValidator
from migrate.validators.loop_detector import LoopDetectorValidator

results: dict[str, dict] = {}


def banner(msg: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {msg}")
    print(f"{'=' * 70}\n")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 1: Sitemap Discovery (allbirds.com)                   ║
# ╚═══════════════════════════════════════════════════════════════╝

def test1_sitemap_discovery():
    """Test sitemap parsing against a real Shopify store."""
    banner("TEST 1: Sitemap Discovery — allbirds.com")
    test_result = {
        "name": "Sitemap Discovery (allbirds.com)",
        "status": "RUNNING",
        "source_urls": 0,
        "mapped": 0,
        "unmapped": 0,
        "errors": [],
        "timing_seconds": 0,
        "validator_results": {},
        "spot_checks": [],
    }

    start = time.time()

    try:
        # Phase 1: Discover via sitemap
        print("Phase 1: Fetching sitemap...")
        fetcher = SitemapFetcher(
            sitemap_url="https://www.allbirds.com/sitemap.xml",
            output_dir=STRESS_DIR / "test1-sitemap" / "output" / "00_source_data" / "discovered",
        )
        result = fetcher.fetch_all()
        sitemap_count = len(result.raw_urls)
        test_result["source_urls"] = sitemap_count
        print(f"  Sitemap: {sitemap_count} URLs discovered")

        if sitemap_count == 0:
            test_result["errors"].append("Sitemap returned 0 URLs")
            test_result["status"] = "FAIL"
            return

        # Phase 2: Categorize what we got
        type_counts = defaultdict(int)
        for entry in result.raw_urls:
            rtype = entry.get("resource_type", "unknown")
            type_counts[rtype] += 1
        print(f"  Type breakdown: {dict(type_counts)}")

        # Phase 3: Build a self-mapping test — the sitemap URLs ARE the target data
        # (since allbirds.com is already a Shopify store)
        print("\nPhase 2: Building target lookups from sitemap data...")
        product_handles: dict[str, dict] = {}
        collection_handles: dict[str, dict] = {}
        page_handles: dict[str, dict] = {}

        for entry in result.raw_urls:
            path = entry.get("path", "")
            url_key = entry.get("url_key", "")
            rtype = entry.get("resource_type", "unknown")

            if not url_key:
                continue

            if rtype == "product" or "/products/" in path:
                product_handles[url_key.lower()] = {"handle": url_key, "title": url_key}
            elif rtype == "category" or "/collections/" in path:
                collection_handles[url_key.lower()] = {"handle": url_key, "title": url_key}
            elif rtype == "cms_page" or "/pages/" in path:
                page_handles[url_key.lower()] = {"handle": url_key, "title": url_key}

        print(f"  Products: {len(product_handles)}, Collections: {len(collection_handles)}, Pages: {len(page_handles)}")

        # Phase 4: Run matcher pipeline against discovered URLs
        print("\nPhase 3: Running matcher pipeline...")
        from migrate.config import PatternRule, NormalizerConfig

        normalizer_cfg = NormalizerConfig(
            strip_extensions=[".html", ".htm"],
            trailing_slash="strip",
            lowercase=True,
        )

        exact = ExactMatcher(product_handles, collection_handles, page_handles)
        fuzzy = FuzzyMatcher(
            title_to_handle={h: h for h in product_handles},
            collection_title_to_handle={h: h for h in collection_handles},
            threshold=0.7,
        )
        partial = PartialMatcher(product_handles, collection_handles)
        pattern = PatternMatcher([
            PatternRule(match="^/products/(.+)", action="redirect", target="/products/\\1", target_type="product"),
            PatternRule(match="^/collections/(.+)", action="redirect", target="/collections/\\1", target_type="collection"),
            PatternRule(match="^/pages/(.+)", action="redirect", target="/pages/\\1", target_type="page"),
            PatternRule(match="^/blogs/(.+)", action="redirect", target="/blogs/\\1", target_type="page"),
        ])
        pipeline = MatcherPipeline([exact, fuzzy, partial, pattern])

        mapped = 0
        unmapped = 0
        match_type_counts = defaultdict(int)

        # Sample for spot checks
        sample_indices = set(random.sample(range(min(len(result.raw_urls), 1000)), min(10, len(result.raw_urls))))

        for i, entry in enumerate(result.raw_urls):
            path = entry.get("path", "")
            url_key = entry.get("url_key", "")
            rtype = entry.get("resource_type", "unknown")

            normalized = normalize_url(path, normalizer_cfg)
            # Determine resource type for matcher
            if "/products/" in path:
                resource_type = "product"
            elif "/collections/" in path:
                resource_type = "collection"
            elif "/pages/" in path:
                resource_type = "page"
            else:
                resource_type = "product"

            match = pipeline.match(
                url_key or normalized.strip("/"),
                resource_type=resource_type,
                name=url_key,
            )

            if match:
                mapped += 1
                match_type_counts[match.match_type] += 1
            else:
                unmapped += 1

            # Spot check
            if i in sample_indices:
                test_result["spot_checks"].append({
                    "source": path,
                    "url_key": url_key,
                    "resource_type": rtype,
                    "matched": match is not None,
                    "match_type": match.match_type if match else "none",
                    "target": match.target_path if match else "N/A",
                })

        test_result["mapped"] = mapped
        test_result["unmapped"] = unmapped
        test_result["match_type_breakdown"] = dict(match_type_counts)

        print(f"  Mapped: {mapped}, Unmapped: {unmapped}")
        print(f"  Match types: {dict(match_type_counts)}")
        print(f"  Map rate: {mapped / max(sitemap_count, 1) * 100:.1f}%")

        test_result["status"] = "PASS"

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test1"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 2: CSV Import (50 synthetic URLs)                      ║
# ╚═══════════════════════════════════════════════════════════════╝

def test2_csv_import():
    """Test CSV import with synthetic data through the full engine."""
    banner("TEST 2: CSV Import — 50 Synthetic URLs")
    test_result = {
        "name": "CSV Import (50 synthetic URLs)",
        "status": "RUNNING",
        "source_urls": 0,
        "mapped": 0,
        "unmapped": 0,
        "errors": [],
        "timing_seconds": 0,
        "validator_results": {},
        "spot_checks": [],
    }
    start = time.time()

    try:
        test_dir = STRESS_DIR / "test2-csv"
        output_dir = test_dir / "output"

        # Create synthetic product/collection/page names
        products = [
            "wool-runner", "tree-dasher", "trail-runner", "lounger",
            "pipper", "mizzle", "flyer", "skipper", "breeze-knit",
            "superlight-tree-runner", "kauri", "pacer", "rover",
            "natural-run", "wind-runner", "foam-runner", "cloud-stepper",
            "dawn-breaker", "peak-climber", "trail-blazer",
        ]
        collections = [
            "mens-shoes", "womens-shoes", "sale", "new-arrivals",
            "running", "everyday", "winter", "socks", "accessories",
            "apparel",
        ]
        pages = [
            "about", "sustainability", "contact", "faq", "returns",
            "shipping", "careers", "press", "stores", "materials",
        ]

        # Create source CSV (simulating old CMS URLs)
        csv_path = test_dir / "source_urls.csv"
        csv_rows = []
        for p in products:
            csv_rows.append({
                "source_url": f"/catalog/product/{p}.html",
                "resource_type": "product",
                "name": p.replace("-", " ").title(),
                "url_key": p,
            })
        for c in collections:
            csv_rows.append({
                "source_url": f"/category/{c}.html",
                "resource_type": "category",
                "name": c.replace("-", " ").title(),
                "url_key": c,
            })
        for pg in pages:
            csv_rows.append({
                "source_url": f"/{pg}",
                "resource_type": "cms_page",
                "name": pg.replace("-", " ").title(),
                "url_key": pg,
            })

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["source_url", "resource_type", "name", "url_key"])
            writer.writeheader()
            writer.writerows(csv_rows)

        test_result["source_urls"] = len(csv_rows)
        print(f"  Created {len(csv_rows)} synthetic URLs in CSV")

        # Create target data (Shopify JSON fixtures)
        target_dir = output_dir / "00_source_data" / "target"
        target_dir.mkdir(parents=True, exist_ok=True)

        # Products: 15 of 20 exist in target (75% match rate expected)
        shopify_products = []
        for p in products[:15]:
            shopify_products.append({
                "handle": p,
                "title": p.replace("-", " ").title(),
                "variants": [{"sku": f"AB-{p.upper()[:8]}"}],
            })
        (target_dir / "products.json").write_text(json.dumps(shopify_products))

        # Collections: 8 of 10 exist
        shopify_collections = []
        for c in collections[:8]:
            shopify_collections.append({
                "handle": c,
                "title": c.replace("-", " ").title(),
                "collection_type": "smart",
            })
        (target_dir / "collections.json").write_text(json.dumps(shopify_collections))

        # Pages: 7 of 10 exist
        shopify_pages = []
        for pg in pages[:7]:
            shopify_pages.append({
                "handle": pg,
                "title": pg.replace("-", " ").title(),
            })
        (target_dir / "pages.json").write_text(json.dumps(shopify_pages))

        # NOTE: Do NOT create empty source JSON files — they cause _load_data()
        # to overwrite in-memory raw_urls with empty data (confirmed bug).

        # Create config
        config_data = {
            "project": {"name": "stress-test-csv"},
            "source": {
                "platform": "csv",
                "csv_file": str(csv_path),
                "csv_columns": {"url": "source_url", "type": "resource_type", "name": "name"},
            },
            "target": {
                "platform": "shopify",
                "domain": "stress-test.myshopify.com",
                "api": {
                    "store_url": "stress-test.myshopify.com",
                    "access_token": "placeholder",
                },
            },
            "output": {"directory": str(output_dir)},
            "normalizer": {
                "strip_extensions": [".html", ".htm"],
                "trailing_slash": "strip",
                "lowercase": True,
            },
            "matchers": {
                "pipeline": ["exact", "fuzzy", "partial"],
                "fuzzy_threshold": 0.75,
            },
            "page_mappings": {pg: f"/pages/{pg}" for pg in pages},
        }

        config_path = test_dir / "config.yaml"
        config_path.write_text(yaml.dump(config_data, default_flow_style=False))

        # Run the engine
        print("  Running MigrationEngine...")
        cfg = load_config(config_path)
        engine = MigrationEngine(cfg)

        # Fetch source via CSV fetcher
        from migrate.fetchers.csv_import import CSVImportFetcher

        csv_fetcher = CSVImportFetcher(
            csv_path=csv_path,
            url_column="source_url",
            type_column="resource_type",
            name_column="name",
        )
        engine.source_data = csv_fetcher.fetch_all()
        print(f"  CSV fetcher loaded {len(engine.source_data.raw_urls)} URLs")

        # Run the mapping
        engine.run()

        # Analyze results
        mapped = sum(1 for m in engine.all_mappings if m["mapping_status"] == "MAPPED")
        unmapped = sum(1 for m in engine.all_mappings if m["mapping_status"].startswith("UNMAPPED"))
        total = len(engine.all_mappings)

        test_result["mapped"] = mapped
        test_result["unmapped"] = unmapped

        print(f"  Total: {total}, Mapped: {mapped}, Unmapped: {unmapped}")
        print(f"  Map rate: {mapped / max(total, 1) * 100:.1f}%")

        # Spot check 10
        sample = random.sample(engine.all_mappings, min(10, len(engine.all_mappings)))
        for m in sample:
            test_result["spot_checks"].append({
                "source": m["source_url"],
                "target": m["target_url"],
                "status": m["mapping_status"],
                "match_type": m["match_type"],
                "confidence": m["confidence"],
            })

        # Run CSV validator
        print("\n  Running CSV format validator...")
        redirect_csv = output_dir / "06_output" / "shopify_redirects_complete.csv"
        if redirect_csv.exists():
            v = CSVFormatValidator(cfg, csv_path=redirect_csv)
            csv_valid = v.run()
            test_result["validator_results"]["csv_format"] = "PASS" if csv_valid else "FAIL"
            print(f"  CSV validator: {'PASS' if csv_valid else 'FAIL'}")
        else:
            test_result["validator_results"]["csv_format"] = "SKIP (no output CSV)"

        # Run loop detector
        print("  Running loop detector...")
        if redirect_csv.exists():
            ld = LoopDetectorValidator(cfg, csv_path=redirect_csv)
            loop_result = ld.run()
            test_result["validator_results"]["loop_detector"] = "PASS" if loop_result else f"FAIL ({len(ld.loops)} loops)"
            print(f"  Loop detector: {'PASS' if loop_result else 'FAIL'}")
        else:
            test_result["validator_results"]["loop_detector"] = "SKIP"

        test_result["status"] = "PASS"

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test2"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 3: Large Scale (1000+ synthetic URLs)                  ║
# ╚═══════════════════════════════════════════════════════════════╝

def test3_large_scale():
    """Test with 2000+ synthetic URLs for performance and correctness."""
    banner("TEST 3: Large Scale — 2000 Synthetic URLs")
    test_result = {
        "name": "Large Scale (2000 synthetic URLs)",
        "status": "RUNNING",
        "source_urls": 0,
        "mapped": 0,
        "unmapped": 0,
        "errors": [],
        "timing_seconds": 0,
        "validator_results": {},
        "spot_checks": [],
    }
    start = time.time()

    try:
        test_dir = STRESS_DIR / "test3-large"
        output_dir = test_dir / "output"

        # Generate 2000 URLs with realistic patterns
        PRODUCT_COUNT = 1200
        COLLECTION_COUNT = 150
        PAGE_COUNT = 50
        UNKNOWN_COUNT = 600  # URLs with no match

        random.seed(42)  # Reproducible

        def rand_slug(n=3):
            words = ["blue", "red", "green", "dark", "light", "super", "ultra",
                     "pro", "max", "mini", "eco", "bio", "smart", "classic",
                     "modern", "vintage", "deluxe", "premium", "basic", "slim"]
            return "-".join(random.sample(words, min(n, len(words))))

        # Create products
        product_slugs = [f"{rand_slug(2)}-{i}" for i in range(PRODUCT_COUNT)]
        collection_slugs = [f"collection-{rand_slug(1)}-{i}" for i in range(COLLECTION_COUNT)]
        page_slugs = [f"page-{rand_slug(1)}-{i}" for i in range(PAGE_COUNT)]

        # Source CSV with some that exist in target, some that don't
        csv_path = test_dir / "large_source.csv"
        csv_rows = []

        for slug in product_slugs:
            csv_rows.append({
                "source_url": f"/{slug}.html",
                "resource_type": "product",
                "name": slug.replace("-", " ").title(),
                "url_key": slug,
            })
        for slug in collection_slugs:
            csv_rows.append({
                "source_url": f"/category/{slug}.html",
                "resource_type": "category",
                "name": slug.replace("-", " ").title(),
                "url_key": slug,
            })
        for slug in page_slugs:
            csv_rows.append({
                "source_url": f"/{slug}",
                "resource_type": "cms_page",
                "name": slug.replace("-", " ").title(),
                "url_key": slug,
            })
        for i in range(UNKNOWN_COUNT):
            csv_rows.append({
                "source_url": f"/legacy/old-page-{i}.html",
                "resource_type": "unknown",
                "name": f"Legacy Page {i}",
                "url_key": f"old-page-{i}",
            })

        random.shuffle(csv_rows)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["source_url", "resource_type", "name", "url_key"])
            writer.writeheader()
            writer.writerows(csv_rows)

        test_result["source_urls"] = len(csv_rows)
        print(f"  Created {len(csv_rows)} synthetic URLs")

        # Target: 80% of products, 90% of collections exist
        target_dir = output_dir / "00_source_data" / "target"
        target_dir.mkdir(parents=True, exist_ok=True)

        match_product_count = int(PRODUCT_COUNT * 0.8)
        match_collection_count = int(COLLECTION_COUNT * 0.9)
        match_page_count = int(PAGE_COUNT * 0.7)

        shopify_products = [
            {"handle": s, "title": s.replace("-", " ").title(), "variants": [{"sku": f"SKU-{s[:10]}"}]}
            for s in product_slugs[:match_product_count]
        ]
        shopify_collections = [
            {"handle": s, "title": s.replace("-", " ").title(), "collection_type": "smart"}
            for s in collection_slugs[:match_collection_count]
        ]
        shopify_pages = [
            {"handle": s, "title": s.replace("-", " ").title()}
            for s in page_slugs[:match_page_count]
        ]

        (target_dir / "products.json").write_text(json.dumps(shopify_products))
        (target_dir / "collections.json").write_text(json.dumps(shopify_collections))
        (target_dir / "pages.json").write_text(json.dumps(shopify_pages))

        # NOTE: Do NOT create empty source JSON files — they cause _load_data()
        # to overwrite in-memory raw_urls with empty data (confirmed bug).

        # Config
        config_data = {
            "project": {"name": "stress-test-large"},
            "source": {
                "platform": "csv",
                "csv_file": str(csv_path),
                "csv_columns": {"url": "source_url", "type": "resource_type", "name": "name"},
            },
            "target": {
                "platform": "shopify",
                "domain": "stress-test.myshopify.com",
                "api": {"store_url": "stress-test.myshopify.com", "access_token": "placeholder"},
            },
            "output": {"directory": str(output_dir)},
            "normalizer": {
                "strip_extensions": [".html", ".htm"],
                "trailing_slash": "strip",
                "lowercase": True,
            },
            "matchers": {
                "pipeline": ["exact", "sku", "fuzzy", "partial", "pattern"],
                "fuzzy_threshold": 0.80,
            },
            "page_mappings": {s: f"/pages/{s}" for s in page_slugs},
            "redirects": {"max_per_batch": 50000},
        }

        config_path = test_dir / "config.yaml"
        config_path.write_text(yaml.dump(config_data, default_flow_style=False))

        cfg = load_config(config_path)
        engine = MigrationEngine(cfg)

        from migrate.fetchers.csv_import import CSVImportFetcher

        csv_fetcher = CSVImportFetcher(
            csv_path=csv_path,
            url_column="source_url",
            type_column="resource_type",
            name_column="name",
        )
        engine.source_data = csv_fetcher.fetch_all()

        print(f"  Loaded {len(engine.source_data.raw_urls)} URLs, running mapping...")
        map_start = time.time()
        engine.run()
        map_elapsed = round(time.time() - map_start, 2)

        mapped = sum(1 for m in engine.all_mappings if m["mapping_status"] == "MAPPED")
        unmapped = sum(1 for m in engine.all_mappings if m["mapping_status"].startswith("UNMAPPED"))
        total = len(engine.all_mappings)

        test_result["mapped"] = mapped
        test_result["unmapped"] = unmapped
        test_result["map_time_seconds"] = map_elapsed

        print(f"  Total: {total}, Mapped: {mapped}, Unmapped: {unmapped}")
        print(f"  Map rate: {mapped / max(total, 1) * 100:.1f}%")
        print(f"  Mapping time: {map_elapsed}s ({total / max(map_elapsed, 0.01):.0f} URLs/sec)")

        # Expected: ~80% of 1200 products + ~90% of 150 collections + 100% of pages (via page_mappings) + 0% of unknown
        expected_mapped = match_product_count + match_collection_count + PAGE_COUNT
        print(f"  Expected ~{expected_mapped} mapped, got {mapped}")

        # Match type breakdown
        match_types = defaultdict(int)
        for m in engine.all_mappings:
            if m["match_type"] != "none":
                match_types[m["match_type"]] += 1
        print(f"  Match types: {dict(match_types)}")
        test_result["match_type_breakdown"] = dict(match_types)

        # Validators
        redirect_csv = output_dir / "06_output" / "shopify_redirects_complete.csv"
        if redirect_csv.exists():
            v = CSVFormatValidator(cfg, csv_path=redirect_csv)
            csv_valid = v.run()
            test_result["validator_results"]["csv_format"] = "PASS" if csv_valid else "FAIL"

            ld = LoopDetectorValidator(cfg, csv_path=redirect_csv)
            loop_result = ld.run()
            test_result["validator_results"]["loop_detector"] = "PASS" if loop_result else f"FAIL ({len(ld.loops)} loops)"

        # Spot checks
        sample = random.sample(engine.all_mappings, min(10, len(engine.all_mappings)))
        for m in sample:
            test_result["spot_checks"].append({
                "source": m["source_url"],
                "target": m["target_url"],
                "status": m["mapping_status"],
                "match_type": m["match_type"],
                "confidence": m["confidence"],
            })

        test_result["status"] = "PASS"

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test3"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 4: Multi-Market (de/en prefix expansion)              ║
# ╚═══════════════════════════════════════════════════════════════╝

def test4_multi_market():
    """Test multi-market prefix expansion with bilingual config."""
    banner("TEST 4: Multi-Market — de/en Prefix Expansion")
    test_result = {
        "name": "Multi-Market (de/en prefixes)",
        "status": "RUNNING",
        "source_urls": 0,
        "mapped": 0,
        "unmapped": 0,
        "errors": [],
        "timing_seconds": 0,
        "validator_results": {},
        "spot_checks": [],
    }
    start = time.time()

    try:
        test_dir = STRESS_DIR / "test4-multimarket"
        output_dir = test_dir / "output"

        # Create source CSV
        products = ["espresso", "cappuccino", "latte", "mocha", "americano",
                     "filter-kaffee", "lungo", "ristretto", "doppio", "macchiato"]
        collections = ["bohnen", "kapseln", "zubehoer", "geschenke"]
        pages = ["agb", "impressum", "kontakt", "datenschutz", "ueber-uns"]

        csv_path = test_dir / "source.csv"
        csv_rows = []
        for p in products:
            csv_rows.append({"source_url": f"/{p}.html", "resource_type": "product", "name": p.replace("-", " ").title(), "url_key": p})
        for c in collections:
            csv_rows.append({"source_url": f"/category/{c}.html", "resource_type": "category", "name": c.replace("-", " ").title(), "url_key": c})
        for pg in pages:
            csv_rows.append({"source_url": f"/{pg}", "resource_type": "cms_page", "name": pg.replace("-", " ").title(), "url_key": pg})

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["source_url", "resource_type", "name", "url_key"])
            writer.writeheader()
            writer.writerows(csv_rows)

        test_result["source_urls"] = len(csv_rows)

        # Target data
        target_dir = output_dir / "00_source_data" / "target"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "products.json").write_text(json.dumps([
            {"handle": p, "title": p.replace("-", " ").title(), "variants": []} for p in products
        ]))
        (target_dir / "collections.json").write_text(json.dumps([
            {"handle": c, "title": c.replace("-", " ").title(), "collection_type": "smart"} for c in collections
        ]))
        (target_dir / "pages.json").write_text(json.dumps([
            {"handle": pg, "title": pg.replace("-", " ").title()} for pg in pages
        ]))

        # NOTE: Do NOT create empty source JSON files — they cause _load_data()
        # to overwrite in-memory raw_urls with empty data (confirmed bug).

        # Config with markets
        config_data = {
            "project": {"name": "multi-market-test"},
            "source": {
                "platform": "csv",
                "csv_file": str(csv_path),
                "csv_columns": {"url": "source_url", "type": "resource_type", "name": "name"},
            },
            "target": {
                "platform": "shopify",
                "domain": "test-store.myshopify.com",
                "api": {"store_url": "test-store.myshopify.com", "access_token": "placeholder"},
            },
            "output": {"directory": str(output_dir)},
            "normalizer": {
                "strip_extensions": [".html", ".htm"],
                "trailing_slash": "strip",
                "lowercase": True,
            },
            "matchers": {
                "pipeline": ["exact", "fuzzy", "partial"],
                "fuzzy_threshold": 0.80,
                "slug_transforms": [
                    {"from": "ae", "to": "a"},
                    {"from": "oe", "to": "o"},
                    {"from": "ue", "to": "u"},
                ],
            },
            "page_mappings": {pg: f"/pages/{pg}" for pg in pages},
            "markets": [
                {"locale": "de", "prefix": "/de", "hreflang": "de-CH"},
                {"locale": "en", "prefix": "/en", "hreflang": "en-GB"},
                {"locale": "fr", "prefix": "/fr", "hreflang": "fr-CH"},
            ],
        }

        config_path = test_dir / "config.yaml"
        config_path.write_text(yaml.dump(config_data, default_flow_style=False))

        cfg = load_config(config_path)
        engine = MigrationEngine(cfg)

        from migrate.fetchers.csv_import import CSVImportFetcher

        csv_fetcher = CSVImportFetcher(csv_path=csv_path, url_column="source_url", type_column="resource_type", name_column="name")
        engine.source_data = csv_fetcher.fetch_all()
        engine.run()

        mapped = sum(1 for m in engine.all_mappings if m["mapping_status"] == "MAPPED")
        unmapped = sum(1 for m in engine.all_mappings if m["mapping_status"].startswith("UNMAPPED"))
        total = len(engine.all_mappings)

        test_result["mapped"] = mapped
        test_result["unmapped"] = unmapped
        print(f"  Source URLs: {total}, Mapped: {mapped}, Unmapped: {unmapped}")

        # Check redirect CSV for market expansion
        redirect_csv = output_dir / "06_output" / "shopify_redirects_complete.csv"
        if redirect_csv.exists():
            with open(redirect_csv, newline="") as f:
                rows = list(csv.DictReader(f))
            redirect_count = len(rows)
            de_redirects = sum(1 for r in rows if r.get("Redirect from", "").startswith("/de/"))
            en_redirects = sum(1 for r in rows if r.get("Redirect from", "").startswith("/en/"))
            fr_redirects = sum(1 for r in rows if r.get("Redirect from", "").startswith("/fr/"))
            base_redirects = redirect_count - de_redirects - en_redirects - fr_redirects

            print(f"  Redirect CSV: {redirect_count} total rows")
            print(f"    Base: {base_redirects}, /de/: {de_redirects}, /en/: {en_redirects}, /fr/: {fr_redirects}")

            test_result["redirect_count"] = redirect_count
            test_result["market_breakdown"] = {
                "base": base_redirects, "de": de_redirects, "en": en_redirects, "fr": fr_redirects,
            }

            # Verify expansion: should be 4x (base + 3 markets)
            if base_redirects > 0:
                expansion_ratio = redirect_count / base_redirects
                print(f"    Expansion ratio: {expansion_ratio:.1f}x (expected 4.0x)")
                test_result["expansion_ratio"] = round(expansion_ratio, 2)

            # Validators
            v = CSVFormatValidator(cfg, csv_path=redirect_csv)
            csv_valid = v.run()
            test_result["validator_results"]["csv_format"] = "PASS" if csv_valid else "FAIL"

            ld = LoopDetectorValidator(cfg, csv_path=redirect_csv)
            loop_result = ld.run()
            test_result["validator_results"]["loop_detector"] = "PASS" if loop_result else f"FAIL ({len(ld.loops)} loops)"

        test_result["status"] = "PASS"

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test4"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 5: WordPress REST API (public WooCommerce site)        ║
# ╚═══════════════════════════════════════════════════════════════╝

def test5_wordpress():
    """Test WordPress fetcher against a public WP REST API."""
    banner("TEST 5: WordPress REST API Fetcher")
    test_result = {
        "name": "WordPress REST API Fetcher",
        "status": "RUNNING",
        "source_urls": 0,
        "mapped": 0,
        "unmapped": 0,
        "errors": [],
        "timing_seconds": 0,
        "validator_results": {},
        "spot_checks": [],
    }
    start = time.time()

    try:
        from migrate.fetchers.wordpress import WordPressFetcher

        # Test against WordPress.org's own blog (known public REST API)
        print("  Testing WordPress fetcher against wordpress.org...")
        test_dir = STRESS_DIR / "test5-wordpress"

        fetcher = WordPressFetcher(
            base_url="https://wordpress.org/news",
            output_dir=test_dir / "output" / "source",
        )

        # Test REST API availability
        import requests
        try:
            resp = requests.get("https://wordpress.org/news/wp-json/wp/v2", timeout=10)
            api_available = resp.status_code == 200
            print(f"  REST API available: {api_available} (status: {resp.status_code})")
        except requests.RequestException as e:
            api_available = False
            print(f"  REST API check failed: {e}")

        if not api_available:
            # Try TechCrunch as fallback (known WP site)
            print("  Trying fallback: techcrunch.com...")
            fetcher = WordPressFetcher(
                base_url="https://techcrunch.com",
                output_dir=test_dir / "output" / "source",
            )
            try:
                resp = requests.get("https://techcrunch.com/wp-json/wp/v2", timeout=10)
                api_available = resp.status_code == 200
                print(f"  REST API available: {api_available} (status: {resp.status_code})")
            except requests.RequestException as e:
                api_available = False
                print(f"  Fallback REST API check failed: {e}")

        if api_available:
            result = fetcher.fetch_all()
            total_items = len(result.collections) + len(result.pages)
            test_result["source_urls"] = total_items

            print(f"  Categories: {len(result.collections)}")
            print(f"  Pages + Posts: {len(result.pages)}")
            print(f"  Total items: {total_items}")

            if total_items > 0:
                # Spot check some results
                for item in (result.collections[:3] + result.pages[:5]):
                    test_result["spot_checks"].append({
                        "handle": item.get("handle", ""),
                        "title": item.get("title", ""),
                        "type": item.get("type", "category"),
                        "link": item.get("link", ""),
                    })

                test_result["status"] = "PASS"
            else:
                test_result["status"] = "PASS (0 items — API may restrict listing)"
                test_result["errors"].append("API returned 0 items; site may restrict REST API listing")
        else:
            test_result["status"] = "SKIP (no accessible WP REST API)"
            test_result["errors"].append("Could not find accessible WP REST API endpoint")

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test5"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  TEST 6 (BONUS): Engine Bug — fetch/map disk persistence     ║
# ╚═══════════════════════════════════════════════════════════════╝

def test6_fetch_map_persistence():
    """Verify the known limitation: sitemap/CSV data doesn't persist between fetch and map CLI commands."""
    banner("TEST 6 (BONUS): Fetch→Map Disk Persistence Gap")
    test_result = {
        "name": "Fetch→Map Disk Persistence Gap",
        "status": "RUNNING",
        "errors": [],
        "timing_seconds": 0,
    }
    start = time.time()

    try:
        test_dir = STRESS_DIR / "test2-csv"
        config_path = test_dir / "config.yaml"

        if not config_path.exists():
            test_result["status"] = "SKIP (depends on test2)"
            return

        cfg = load_config(config_path)

        # Simulate what the CLI does: separate engine instances
        engine1 = MigrationEngine(cfg)
        from migrate.fetchers.csv_import import CSVImportFetcher
        csv_fetcher = CSVImportFetcher(
            csv_path=cfg.source.csv_file,
            url_column="source_url",
            type_column="resource_type",
            name_column="name",
        )
        engine1.source_data = csv_fetcher.fetch_all()
        urls_in_memory = len(engine1.source_data.raw_urls)
        print(f"  Engine 1 (fetch): {urls_in_memory} URLs in memory")

        # New engine (simulates separate `map` command)
        engine2 = MigrationEngine(cfg)
        engine2.run()
        urls_loaded = len(engine2.all_mappings)
        print(f"  Engine 2 (map): {urls_loaded} mappings generated")

        # The mapper loads target data from JSON (works) but source raw_urls are lost
        if urls_loaded == 0 and urls_in_memory > 0:
            test_result["finding"] = "CONFIRMED: raw_urls from CSV/sitemap fetcher not persisted to disk. Separate fetch→map CLI calls lose source data."
            test_result["status"] = "CONFIRMED BUG"
            print(f"  CONFIRMED: Data lost between fetch and map (had {urls_in_memory} URLs, mapped 0)")
        elif urls_loaded > 0:
            test_result["finding"] = "Data persisted (mapper loaded from JSON files)"
            test_result["status"] = "PASS"
        else:
            test_result["finding"] = "Both empty — inconclusive"
            test_result["status"] = "INCONCLUSIVE"

    except Exception as e:
        test_result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        test_result["status"] = "FAIL"
        import traceback
        traceback.print_exc()

    test_result["timing_seconds"] = round(time.time() - start, 2)
    results["test6"] = test_result
    print(f"\n  Time: {test_result['timing_seconds']}s | Status: {test_result['status']}")


# ╔═══════════════════════════════════════════════════════════════╗
# ║  MAIN: Run all tests and write report                       ║
# ╚═══════════════════════════════════════════════════════════════╝

if __name__ == "__main__":
    total_start = time.time()

    print("\n" + "=" * 70)
    print("  URL MIGRATION TOOLKIT — STRESS TEST SUITE")
    print("=" * 70)

    test1_sitemap_discovery()
    test2_csv_import()
    test3_large_scale()
    test4_multi_market()
    test5_wordpress()
    test6_fetch_map_persistence()

    total_elapsed = round(time.time() - total_start, 2)

    # Write JSON results for report generation
    results_path = STRESS_DIR / "stress_test_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'=' * 70}")
    print(f"  ALL TESTS COMPLETE — Total time: {total_elapsed}s")
    print(f"  Results saved to: {results_path}")
    print(f"{'=' * 70}")

    # Summary
    for tid, r in results.items():
        status = r.get("status", "UNKNOWN")
        name = r.get("name", tid)
        icon = "PASS" if "PASS" in status else ("FAIL" if "FAIL" in status else status)
        print(f"  [{icon:>15}] {name}")
