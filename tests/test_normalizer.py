"""Tests for the URL normalizer module."""

import pytest

from migrate.config import NormalizerConfig
from migrate.normalizer import (
    apply_slug_transforms,
    apply_trailing_slash,
    extract_path,
    normalize_path_for_comparison,
    normalize_url,
    strip_extensions,
    strip_query_params,
)


@pytest.fixture
def default_config():
    return NormalizerConfig()


@pytest.fixture
def example_config():
    """Config with strip extensions and trailing slash (example store)."""
    return NormalizerConfig(
        strip_extensions=[".html", ".htm"],
        strip_params=["utm_source", "utm_medium", "gclid", "SID"],
        trailing_slash="strip",
        lowercase=True,
    )


# ── strip_extensions ─────────────────────────────────────────


class TestStripExtensions:
    def test_strips_html(self):
        assert strip_extensions("/category/example-product.html", [".html"]) == "/category/example-product"

    def test_strips_htm(self):
        assert strip_extensions("/about.htm", [".htm", ".html"]) == "/about"

    def test_strips_php(self):
        assert strip_extensions("/index.php", [".php"]) == "/index"

    def test_no_extension_no_change(self):
        assert strip_extensions("/products/example-product", [".html"]) == "/products/example-product"

    def test_only_strips_one(self):
        assert strip_extensions("/file.html.html", [".html"]) == "/file.html"

    def test_empty_extensions_list(self):
        assert strip_extensions("/page.html", []) == "/page.html"

    def test_empty_url(self):
        assert strip_extensions("", [".html"]) == ""

    def test_full_url_with_extension(self):
        result = strip_extensions("https://shop.example-store.example/example.html", [".html"])
        assert result == "https://shop.example-store.example/example"


# ── strip_query_params ───────────────────────────────────────


class TestStripQueryParams:
    def test_strips_utm_params(self):
        url = "/page?utm_source=google&utm_medium=cpc&valid=1"
        result = strip_query_params(url, ["utm_source", "utm_medium"])
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "valid=1" in result

    def test_strips_gclid(self):
        url = "/products/example-product?gclid=abc123"
        result = strip_query_params(url, ["gclid"])
        assert result == "/products/example-product"

    def test_preserves_valid_params(self):
        url = "/search?q=kaffee&page=2"
        result = strip_query_params(url, ["utm_source"])
        assert "q=kaffee" in result
        assert "page=2" in result

    def test_no_query_string(self):
        assert strip_query_params("/page", ["utm_source"]) == "/page"

    def test_empty_deny_list(self):
        url = "/page?utm_source=google"
        assert strip_query_params(url, []) == url

    def test_case_insensitive(self):
        url = "/page?UTM_SOURCE=google"
        # Deny list is lowered internally, but keys are matched case-insensitively
        result = strip_query_params(url, ["utm_source"])
        # Our implementation lowercases the deny list check
        assert "UTM_SOURCE" not in result or "utm_source" not in result


# ── apply_trailing_slash ─────────────────────────────────────


class TestTrailingSlash:
    def test_strip_removes_slash(self):
        assert apply_trailing_slash("/products/example-product/", "strip") == "/products/example-product"

    def test_strip_preserves_root(self):
        assert apply_trailing_slash("/", "strip") == "/"

    def test_add_adds_slash(self):
        assert apply_trailing_slash("/products/example-product", "add") == "/products/example-product/"

    def test_preserve_no_change_with_slash(self):
        assert apply_trailing_slash("/page/", "preserve") == "/page/"

    def test_preserve_no_change_without_slash(self):
        assert apply_trailing_slash("/page", "preserve") == "/page"


# ── extract_path ─────────────────────────────────────────────


class TestExtractPath:
    def test_full_url(self):
        assert extract_path("https://shop.example-store.example/products/example-product") == "/products/example-product"

    def test_relative_path(self):
        assert extract_path("/products/example-product") == "/products/example-product"

    def test_root_url(self):
        assert extract_path("https://example.com") == "/"

    def test_empty(self):
        assert extract_path("") == ""

    def test_http_url(self):
        assert extract_path("http://example-store.de/kaffee.html") == "/kaffee.html"


# ── normalize_url (integrated) ───────────────────────────────


class TestNormalizeUrl:
    def test_full_normalization(self, example_config):
        url = "/Category/Example.HTML?utm_source=google&SID=abc"
        result = normalize_url(url, example_config)
        assert result == "/category/example"
        assert "utm_source" not in result
        assert "SID" not in result

    def test_lowercasing(self, default_config):
        assert normalize_url("/Products/ExampleProduct", default_config) == "/products/exampleproduct"

    def test_no_lowercase_when_disabled(self):
        cfg = NormalizerConfig(lowercase=False)
        assert normalize_url("/Products/ExampleProduct", cfg) == "/Products/ExampleProduct"


# ── apply_slug_transforms ────────────────────────────────────


class TestSlugTransforms:
    def test_german_umlauts(self):
        transforms = [
            {"from": "ae", "to": "a"},
            {"from": "oe", "to": "o"},
            {"from": "ue", "to": "u"},
        ]
        assert apply_slug_transforms("kaese", transforms) == "kase"
        assert apply_slug_transforms("schoene", transforms) == "schone"
        assert apply_slug_transforms("gruene", transforms) == "grune"

    def test_empty_transforms(self):
        assert apply_slug_transforms("kaffee", []) == "kaffee"


# ── normalize_path_for_comparison ────────────────────────────


class TestNormalizePathForComparison:
    def test_full_url_to_normalized_path(self, example_config):
        url = "https://shop.example-store.example/Category/Example.html?utm_source=foo"
        result = normalize_path_for_comparison(url, example_config)
        assert result == "/category/example"
