"""Tests for the config loading system."""

import os
from pathlib import Path

import pytest
import yaml

from migrate.config import MigrationConfig, load_config


@pytest.fixture
def minimal_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "project": {"name": "test"},
                "source": {"platform": "csv"},
                "target": {"platform": "shopify", "domain": "test.myshopify.com"},
            }
        )
    )
    return config_path


@pytest.fixture
def turm_config(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "project": {"name": "turm-kaffee"},
                "source": {
                    "platform": "magento",
                    "domains": ["shop.turmkaffee.ch", "turmkaffee.de", "turmkaffee.at"],
                },
                "target": {"platform": "shopify", "domain": "shop.turmkaffee.ch"},
                "normalizer": {"strip_extensions": [".html"], "trailing_slash": "strip"},
                "matchers": {
                    "pipeline": ["exact", "sku", "fuzzy", "partial", "pattern"],
                    "fuzzy_threshold": 0.85,
                    "slug_transforms": [
                        {"from": "ae", "to": "a"},
                        {"from": "oe", "to": "o"},
                    ],
                },
                "page_mappings": {"agb": "/pages/agb", "impressum": "/pages/impressum"},
            }
        )
    )
    return config_path


class TestConfigLoading:
    def test_load_minimal_config(self, minimal_config):
        cfg = load_config(minimal_config)
        assert cfg.project.name == "test"
        assert cfg.source.platform == "csv"
        assert cfg.target.domain == "test.myshopify.com"

    def test_load_turm_config(self, turm_config):
        cfg = load_config(turm_config)
        assert cfg.project.name == "turm-kaffee"
        assert len(cfg.source.domains) == 3
        assert "shop.turmkaffee.ch" in cfg.source.domains
        assert len(cfg.matchers.slug_transforms) == 2
        assert cfg.matchers.fuzzy_threshold == 0.85
        assert cfg.page_mappings["agb"] == "/pages/agb"

    def test_defaults_applied(self, minimal_config):
        cfg = load_config(minimal_config)
        assert cfg.normalizer.trailing_slash == "strip"
        assert cfg.normalizer.lowercase is True
        assert cfg.redirects.default_type == 301
        assert cfg.redirects.max_per_batch == 10000
        assert "exact" in cfg.matchers.pipeline

    def test_env_var_interpolation(self, tmp_path):
        os.environ["TEST_TOKEN"] = "secret123"
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "target": {
                        "api": {"access_token": "${TEST_TOKEN}"},
                    },
                }
            )
        )
        cfg = load_config(config_path)
        assert cfg.target.api.access_token == "secret123"
        del os.environ["TEST_TOKEN"]

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/config.yaml")

    def test_empty_config_uses_defaults(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("{}")
        cfg = load_config(config_path)
        assert cfg.project.name == "migration"
        assert cfg.source.platform == "magento"
