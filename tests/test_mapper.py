"""Tests for the core mapper (MigrationEngine)."""

import csv
import json
from pathlib import Path

import pytest

from migrate.config import MigrationConfig, load_config
from migrate.mapper import MigrationEngine


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project structure with fixture data."""
    output_dir = tmp_path / "output"
    source_dir = output_dir / "00_source_data" / "source"
    target_dir = output_dir / "00_source_data" / "target"
    source_dir.mkdir(parents=True)
    target_dir.mkdir(parents=True)

    # Source: Magento products
    magento_products = [
        {
            "id": 1,
            "sku": "TK-KEN-250",
            "name": "Kenner Kaffee",
            "custom_attributes": [{"attribute_code": "url_key", "value": "kenner"}],
        },
        {
            "id": 2,
            "sku": "TK-CRE-500",
            "name": "Crema Kaffee",
            "custom_attributes": [{"attribute_code": "url_key", "value": "crema"}],
        },
        {
            "id": 3,
            "sku": "TK-UNK-100",
            "name": "Mystery Blend",
            "custom_attributes": [{"attribute_code": "url_key", "value": "mystery-blend"}],
        },
    ]
    (source_dir / "products.json").write_text(json.dumps(magento_products))
    (source_dir / "categories.json").write_text(json.dumps({}))
    (source_dir / "cms_pages.json").write_text(json.dumps([]))

    # Target: Shopify products
    shopify_products = [
        {"handle": "kenner", "title": "Kenner Kaffee", "variants": [{"sku": "TK-KEN-250"}]},
        {"handle": "crema", "title": "Crema Kaffee", "variants": [{"sku": "TK-CRE-500"}]},
    ]
    shopify_collections = [
        {"handle": "bohnen", "title": "Kaffeebohnen", "collection_type": "smart"},
    ]
    shopify_pages = [
        {"handle": "agb", "title": "AGB"},
        {"handle": "impressum", "title": "Impressum"},
    ]

    (target_dir / "products.json").write_text(json.dumps(shopify_products))
    (target_dir / "collections.json").write_text(json.dumps(shopify_collections))
    (target_dir / "pages.json").write_text(json.dumps(shopify_pages))

    # Config
    config_data = {
        "project": {"name": "test"},
        "source": {"platform": "magento", "domains": ["example.com"]},
        "target": {"platform": "shopify", "domain": "shop.example.com"},
        "output": {"directory": str(output_dir)},
        "page_mappings": {"agb": "/pages/agb"},
    }
    import yaml

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    return tmp_path, config_path


class TestMigrationEngine:
    def test_end_to_end_mapping(self, tmp_project):
        tmp_path, config_path = tmp_project
        config = load_config(config_path)
        engine = MigrationEngine(config)
        engine.run()

        # Check output files were created
        output_dir = Path(config.output.directory)
        redirect_csv = output_dir / "06_output" / "shopify_redirects_complete.csv"
        assert redirect_csv.exists()

        # Read and verify
        with open(redirect_csv, newline="") as f:
            rows = list(csv.DictReader(f))

        # kenner and crema should be mapped
        # Source paths retain .html (that's what needs redirecting)
        sources = [r["Redirect from"] for r in rows]
        assert "/kenner.html" in sources
        assert "/crema.html" in sources

    def test_unmapped_urls_created(self, tmp_project):
        tmp_path, config_path = tmp_project
        config = load_config(config_path)
        engine = MigrationEngine(config)
        engine.run()

        unmapped_csv = Path(config.output.directory) / "03_mapping_rules" / "unmapped_urls.csv"
        assert unmapped_csv.exists()

        with open(unmapped_csv, newline="") as f:
            rows = list(csv.DictReader(f))

        # mystery-blend has no Shopify match
        unmapped_sources = [r["source_url"] for r in rows]
        assert any("mystery-blend" in s for s in unmapped_sources)

    def test_dry_run_no_files(self, tmp_project):
        tmp_path, config_path = tmp_project
        config = load_config(config_path)
        engine = MigrationEngine(config, dry_run=True)
        engine.run()

        redirect_csv = Path(config.output.directory) / "06_output" / "shopify_redirects_complete.csv"
        assert not redirect_csv.exists()

    def test_loop_detection(self, tmp_project):
        """Verify the engine's internal loop detection works."""
        tmp_path, config_path = tmp_project
        config = load_config(config_path)
        engine = MigrationEngine(config)

        # Simulate a mapping with a loop
        engine.all_mappings = [
            {"source_url": "https://ex.com/a", "target_url": "https://shop.ex.com/b", "mapping_status": "MAPPED"},
            {"source_url": "https://ex.com/b", "target_url": "https://shop.ex.com/a", "mapping_status": "MAPPED"},
        ]
        loops = engine._detect_loops()
        assert len(loops) > 0
