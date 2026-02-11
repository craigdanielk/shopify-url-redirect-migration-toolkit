"""Tests for the Sitemap fetcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import Element, SubElement, tostring

import pytest

from migrate.fetchers.sitemap import SitemapFetcher, _guess_type


class TestGuessType:
    def test_product(self):
        assert _guess_type("/products/cool-hat") == "product"

    def test_category(self):
        assert _guess_type("/categories/hats") == "category"

    def test_page(self):
        assert _guess_type("/pages/about") == "cms_page"

    def test_blog(self):
        assert _guess_type("/blog/my-post") == "blog"

    def test_unknown(self):
        assert _guess_type("/foobar") == "unknown"


class TestSitemapFetcher:
    def _make_urlset_xml(self, urls: list[str]) -> bytes:
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = Element(f"{{{ns}}}urlset")
        for url in urls:
            url_elem = SubElement(root, f"{{{ns}}}url")
            loc = SubElement(url_elem, f"{{{ns}}}loc")
            loc.text = url
        return tostring(root)

    def _make_sitemap_index_xml(self, urls: list[str]) -> bytes:
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = Element(f"{{{ns}}}sitemapindex")
        for url in urls:
            sitemap = SubElement(root, f"{{{ns}}}sitemap")
            loc = SubElement(sitemap, f"{{{ns}}}loc")
            loc.text = url
        return tostring(root)

    @patch("migrate.fetchers.sitemap.SitemapFetcher._fetch_xml")
    def test_fetch_urlset(self, mock_fetch_xml):
        """Test parsing a simple URL set sitemap."""
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = Element(f"{{{ns}}}urlset")
        for url in ["https://example.com/about", "https://example.com/contact"]:
            url_elem = SubElement(root, f"{{{ns}}}url")
            loc = SubElement(url_elem, f"{{{ns}}}loc")
            loc.text = url

        mock_fetch_xml.return_value = root
        fetcher = SitemapFetcher(sitemap_url="https://example.com/sitemap.xml")
        result = fetcher.fetch_all()
        assert len(result.raw_urls) == 2

    @patch("migrate.fetchers.sitemap.SitemapFetcher._fetch_xml")
    def test_fetch_empty(self, mock_fetch_xml):
        mock_fetch_xml.return_value = None
        fetcher = SitemapFetcher(sitemap_url="https://example.com/sitemap.xml")
        result = fetcher.fetch_all()
        assert len(result.raw_urls) == 0

    @patch("migrate.fetchers.sitemap.SitemapFetcher._fetch_xml")
    def test_deduplication(self, mock_fetch_xml):
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        root = Element(f"{{{ns}}}urlset")
        for url in [
            "https://example.com/about",
            "https://example.com/about/",
            "https://example.com/About",
        ]:
            url_elem = SubElement(root, f"{{{ns}}}url")
            loc = SubElement(url_elem, f"{{{ns}}}loc")
            loc.text = url

        mock_fetch_xml.return_value = root
        fetcher = SitemapFetcher(sitemap_url="https://example.com/sitemap.xml")
        result = fetcher.fetch_all()
        assert len(result.raw_urls) == 1
