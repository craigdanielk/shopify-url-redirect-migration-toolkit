"""Tests for the Shopify uploader."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from migrate.config import MigrationConfig
from migrate.uploaders.shopify import ShopifyUploader


@pytest.fixture
def config(tmp_path: Path) -> MigrationConfig:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "06_output").mkdir(parents=True)
    return MigrationConfig(
        target={
            "platform": "shopify",
            "domain": "test.myshopify.com",
            "api": {
                "store_url": "test.myshopify.com",
                "access_token": "fake-token",
                "api_version": "2024-10",
            },
        },
        output={"directory": str(output_dir)},
    )


@pytest.fixture
def csv_file(config: MigrationConfig) -> Path:
    csv_path = Path(config.output.directory) / "06_output" / "shopify_redirects_complete.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Redirect from", "Redirect to"])
        writer.writerow(["/old-product", "/products/new-product"])
        writer.writerow(["/old-page", "/pages/new-page"])
    return csv_path


class TestShopifyUploader:
    def test_load_redirects(self, config, csv_file):
        uploader = ShopifyUploader(config, csv_path=csv_file)
        redirects = uploader._load_redirects_from_csv()
        assert len(redirects) == 2
        assert redirects[0]["source"] == "/old-product"
        assert redirects[0]["target"] == "/products/new-product"

    def test_dry_run_no_api_calls(self, config, csv_file):
        uploader = ShopifyUploader(config, csv_path=csv_file)
        # Should succeed without any real API calls
        success = uploader.upload(dry_run=True)
        assert success is True
        assert len(uploader.created_ids) == 0

    def test_flatten_chains(self, config, csv_file):
        uploader = ShopifyUploader(config, csv_path=csv_file)
        existing = {
            "/products/new-product": {
                "id": 1,
                "target": "/products/final-product",
            }
        }
        redirects = [{"source": "/old-product", "target": "/products/new-product"}]
        result = uploader._flatten_chains(redirects, existing)
        assert result[0]["target"] == "/products/final-product"

    def test_flatten_chains_detects_cycles(self, config, csv_file):
        uploader = ShopifyUploader(config, csv_path=csv_file)
        # A → B, B → A (cycle)
        existing = {
            "/b": {"id": 1, "target": "/a"},
        }
        redirects = [{"source": "/a", "target": "/b"}]
        result = uploader._flatten_chains(redirects, existing)
        # Should not infinite loop — just return /b since cycle detected
        assert len(result) == 1

    def test_rollback_no_manifest(self, config, csv_file):
        uploader = ShopifyUploader(config, csv_path=csv_file)
        success = uploader.rollback()
        assert success is False

    def test_rollback_empty_manifest(self, config, csv_file):
        manifest_path = Path(config.output.directory) / "upload_manifest.json"
        manifest_path.write_text(json.dumps({"created_ids": []}))
        uploader = ShopifyUploader(config, csv_path=csv_file)
        success = uploader.rollback()
        assert success is True
