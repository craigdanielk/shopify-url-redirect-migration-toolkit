"""Tests for multi-market / bilingual support."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

import pytest

from migrate.config import MigrationConfig, load_config
from migrate.mapper import MigrationEngine


@pytest.fixture
def market_config(tmp_path: Path) -> MigrationConfig:
    """Config with two markets defined."""
    return MigrationConfig(
        project={"name": "market-test"},
        target={
            "platform": "shopify",
            "domain": "test.myshopify.com",
            "api": {
                "store_url": "test.myshopify.com",
                "access_token": "fake",
            },
        },
        output={"directory": str(tmp_path / "output")},
        markets=[
            {"locale": "de", "prefix": "/de", "hreflang": "de-CH"},
            {"locale": "en", "prefix": "/en", "hreflang": "en-GB"},
        ],
    )


class TestMultiMarketConfig:
    def test_config_parses_markets(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            """
project:
  name: market-test
markets:
  - locale: de
    prefix: /de
    hreflang: de-CH
  - locale: en
    prefix: /en
    hreflang: en-GB
""",
            encoding="utf-8",
        )
        cfg = load_config(config_yaml)
        assert len(cfg.markets) == 2
        assert cfg.markets[0].locale == "de"
        assert cfg.markets[0].prefix == "/de"
        assert cfg.markets[1].hreflang == "en-GB"

    def test_no_markets_defaults_empty(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("project:\n  name: test\n", encoding="utf-8")
        cfg = load_config(config_yaml)
        assert cfg.markets == []


class TestMarketPrefixExpansion:
    def test_expand_redirects(self, market_config):
        engine = MigrationEngine(market_config)
        redirects = [
            {"Redirect from": "/old-product", "Redirect to": "/products/new"},
            {"Redirect from": "/old-page", "Redirect to": "/pages/about"},
        ]
        expanded = engine._apply_market_prefixes(redirects)
        # 2 original + 2 * 2 markets = 6
        assert len(expanded) == 6

        # Check that locale prefixes are applied
        prefixed = [r for r in expanded if r["Redirect from"].startswith("/de/")]
        assert len(prefixed) == 2
        assert prefixed[0]["Redirect from"] == "/de/old-product"
        assert prefixed[0]["Redirect to"] == "/de/products/new"

    def test_no_expansion_without_markets(self):
        config = MigrationConfig(
            project={"name": "no-market"},
            output={"directory": "/tmp/test"},
        )
        engine = MigrationEngine(config)
        redirects = [
            {"Redirect from": "/old", "Redirect to": "/new"},
        ]
        result = engine._apply_market_prefixes(redirects)
        assert len(result) == 1  # No expansion
