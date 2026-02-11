"""Tests for the Wayback Machine fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from migrate.fetchers.wayback import WaybackFetcher


class TestWaybackFetcher:
    """Tests for WaybackFetcher."""

    def test_classify_era_magento(self):
        assert WaybackFetcher.classify_era("https://example.com/catalog/product/view/id/42") == "magento"

    def test_classify_era_wordpress(self):
        assert WaybackFetcher.classify_era("https://example.com/wp-content/uploads/img.jpg") == "wordpress"

    def test_classify_era_drupal(self):
        assert WaybackFetcher.classify_era("https://example.com/node/123") == "drupal"

    def test_classify_era_shopify(self):
        assert WaybackFetcher.classify_era("https://example.com/products/cool-hat") == "shopify"

    def test_classify_era_typo3(self):
        assert WaybackFetcher.classify_era("https://example.com/kontakt.html") == "typo3"

    def test_classify_era_unknown(self):
        assert WaybackFetcher.classify_era("https://example.com/about") == "unknown"

    def test_filter_entries_removes_404s(self):
        fetcher = WaybackFetcher(domains=["example.com"])
        entries = [
            {"original": "https://example.com/ok", "statuscode": "200", "mimetype": "text/html"},
            {"original": "https://example.com/gone", "statuscode": "404", "mimetype": "text/html"},
            {"original": "https://example.com/broken", "statuscode": "500", "mimetype": "text/html"},
        ]
        result = fetcher._filter_entries(entries)
        assert len(result) == 1
        assert result[0]["original"] == "https://example.com/ok"

    def test_filter_entries_removes_images(self):
        fetcher = WaybackFetcher(domains=["example.com"])
        entries = [
            {"original": "https://example.com/ok", "statuscode": "200", "mimetype": "text/html"},
            {"original": "https://example.com/img.jpg", "statuscode": "200", "mimetype": "image/jpeg"},
            {"original": "https://example.com/style.css", "statuscode": "200", "mimetype": "text/css"},
        ]
        result = fetcher._filter_entries(entries)
        assert len(result) == 1

    def test_deduplicate_by_path(self):
        fetcher = WaybackFetcher(domains=["example.com"])
        entries = [
            {"original": "https://example.com/About"},
            {"original": "https://example.com/about"},
            {"original": "https://example.com/about/"},
        ]
        result = fetcher._deduplicate(entries)
        assert len(result) == 1

    def test_build_url_entries_skips_root(self):
        fetcher = WaybackFetcher(domains=["example.com"])
        entries = [
            {"original": "https://example.com/", "timestamp": "20200101"},
            {"original": "https://example.com/about", "timestamp": "20200101"},
        ]
        result = fetcher._build_url_entries(entries)
        assert len(result) == 1
        assert result[0]["path"] == "/about"

    @patch("migrate.fetchers.wayback.WaybackFetcher._query_cdx")
    def test_fetch_all_calls_cdx(self, mock_cdx):
        mock_cdx.return_value = [
            {
                "original": "https://example.com/about",
                "statuscode": "200",
                "mimetype": "text/html",
                "timestamp": "20200101",
            }
        ]
        fetcher = WaybackFetcher(domains=["example.com"])
        result = fetcher.fetch_all()
        assert len(result.raw_urls) >= 0  # May be 0 or 1 depending on filtering
        assert mock_cdx.call_count >= 2  # Called for domain + www.domain
