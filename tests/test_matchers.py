"""Tests for matcher modules."""

import pytest

from migrate.config import PatternRule
from migrate.matchers.exact import ExactMatcher
from migrate.matchers.fuzzy import FuzzyMatcher
from migrate.matchers.partial import PartialMatcher
from migrate.matchers.pattern import PatternMatcher
from migrate.matchers.pipeline import MatcherPipeline
from migrate.matchers.sku import SKUMatcher


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def product_handles():
    return {
        "kenner": {"handle": "kenner", "title": "Kenner Kaffee"},
        "crema": {"handle": "crema", "title": "Crema Kaffee"},
        "espresso": {"handle": "espresso", "title": "Espresso Blend"},
        "mount-kenya-selection": {"handle": "mount-kenya-selection", "title": "Mount Kenya Selection"},
    }


@pytest.fixture
def collection_handles():
    return {
        "bohnen": {"handle": "bohnen", "title": "Kaffeebohnen"},
        "kapseln": {"handle": "kapseln", "title": "Kapseln"},
        "geschenke": {"handle": "geschenke", "title": "Geschenke"},
    }


@pytest.fixture
def sku_map():
    return {
        "tk-kenner-250": "kenner",
        "tk-crema-500": "crema",
        "tk-esp-250": "espresso",
    }


@pytest.fixture
def title_map():
    return {
        "kenner kaffee": "kenner",
        "crema kaffee": "crema",
        "espresso blend": "espresso",
    }


# ── ExactMatcher ─────────────────────────────────────────────


class TestExactMatcher:
    def test_exact_product_match(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        result = m.match("kenner", resource_type="product")
        assert result is not None
        assert result.handle == "kenner"
        assert result.match_type == "exact"
        assert result.confidence == 1.0

    def test_no_match(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        result = m.match("nonexistent", resource_type="product")
        assert result is None

    def test_case_insensitive(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        result = m.match("KENNER", resource_type="product")
        assert result is not None
        assert result.handle == "kenner"

    def test_collection_match(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        result = m.match("bohnen", resource_type="collection")
        assert result is not None
        assert result.target_type == "collection"
        assert result.target_path == "/collections/bohnen"

    def test_collection_normalized_match(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        # Should match via normalized comparison (strip - and _)
        collection_handles["kaffee-bohnen"] = {"handle": "kaffee-bohnen", "title": "Kaffee Bohnen"}
        m2 = ExactMatcher(product_handles, collection_handles)
        result = m2.match("kaffee_bohnen", resource_type="collection")
        assert result is not None
        assert result.match_type == "normalized"

    def test_empty_url_key(self, product_handles, collection_handles):
        m = ExactMatcher(product_handles, collection_handles)
        assert m.match("", resource_type="product") is None


# ── SKUMatcher ───────────────────────────────────────────────


class TestSKUMatcher:
    def test_direct_sku_match(self, sku_map):
        m = SKUMatcher(sku_map)
        result = m.match("anything", sku="tk-kenner-250", resource_type="product")
        assert result is not None
        assert result.handle == "kenner"
        assert result.match_type == "sku"
        assert result.confidence == 0.95

    def test_sku_from_magento_id_map(self, sku_map):
        magento_id_map = {"42": {"id": "42", "sku": "tk-crema-500", "name": "Crema", "url_key": "crema"}}
        m = SKUMatcher(sku_map, magento_id_map=magento_id_map)
        result = m.match("crema", product_id="42", resource_type="product")
        assert result is not None
        assert result.handle == "crema"

    def test_no_match_for_collections(self, sku_map):
        m = SKUMatcher(sku_map)
        result = m.match("kenner", sku="tk-kenner-250", resource_type="collection")
        assert result is None

    def test_no_sku_match(self, sku_map):
        m = SKUMatcher(sku_map)
        result = m.match("unknown", resource_type="product")
        assert result is None


# ── FuzzyMatcher ─────────────────────────────────────────────


class TestFuzzyMatcher:
    def test_exact_name_match(self, title_map):
        m = FuzzyMatcher(title_map, threshold=0.85)
        result = m.match("kenner", name="Kenner Kaffee", resource_type="product")
        assert result is not None
        assert result.handle == "kenner"
        assert result.confidence >= 0.85

    def test_close_name_match(self, title_map):
        m = FuzzyMatcher(title_map, threshold=0.7)
        result = m.match("kenner", name="Kenner Kaffe", resource_type="product")
        assert result is not None

    def test_below_threshold(self, title_map):
        m = FuzzyMatcher(title_map, threshold=0.95)
        result = m.match("x", name="Something Completely Different", resource_type="product")
        assert result is None

    def test_no_name(self, title_map):
        m = FuzzyMatcher(title_map)
        result = m.match("kenner", resource_type="product")
        assert result is None


# ── PartialMatcher ───────────────────────────────────────────


class TestPartialMatcher:
    def test_url_key_in_handle(self, product_handles, collection_handles):
        m = PartialMatcher(product_handles, collection_handles)
        result = m.match("kenya", resource_type="product")
        assert result is not None
        assert result.handle == "mount-kenya-selection"
        assert result.confidence == 0.7

    def test_handle_in_url_key(self, product_handles, collection_handles):
        m = PartialMatcher(product_handles, collection_handles)
        result = m.match("kenner-bohnen-250g", resource_type="product")
        assert result is not None
        assert result.handle == "kenner"

    def test_collection_partial(self, product_handles, collection_handles):
        m = PartialMatcher(product_handles, collection_handles)
        result = m.match("kaffee-bohnen", resource_type="collection")
        assert result is not None
        assert result.target_type == "collection"


# ── PatternMatcher ───────────────────────────────────────────


class TestPatternMatcher:
    def test_redirect_pattern(self):
        rules = [PatternRule(match="^/catalogsearch/", action="redirect", target="/search")]
        m = PatternMatcher(rules)
        result = m.match("/catalogsearch/result/?q=kaffee")
        assert result is not None
        assert result.target_path == "/search"
        assert result.match_type == "pattern"

    def test_id_lookup_pattern(self):
        rules = [
            PatternRule(
                match=r"^/catalog/product/view/id/(\d+)",
                action="lookup_by_id",
                target_type="product",
            )
        ]
        m = PatternMatcher(rules)
        result = m.match("/catalog/product/view/id/42")
        assert result is not None
        assert result.handle == "42"
        assert result.match_type == "pattern_id_lookup"

    def test_gone_pattern(self):
        rules = [PatternRule(match="^/discontinued", action="gone")]
        m = PatternMatcher(rules)
        result = m.match("/discontinued/old-product")
        assert result is not None
        assert result.match_type == "pattern_gone"

    def test_no_match(self):
        rules = [PatternRule(match="^/only-this", action="redirect", target="/that")]
        m = PatternMatcher(rules)
        assert m.match("/something-else") is None

    def test_empty_url(self):
        rules = [PatternRule(match=".*", action="redirect", target="/")]
        m = PatternMatcher(rules)
        assert m.match("") is None


# ── Pipeline ─────────────────────────────────────────────────


class TestPipeline:
    def test_pipeline_returns_first_match(self, product_handles, collection_handles, sku_map, title_map):
        exact = ExactMatcher(product_handles, collection_handles)
        sku = SKUMatcher(sku_map)
        fuzzy = FuzzyMatcher(title_map)

        pipeline = MatcherPipeline([exact, sku, fuzzy])
        assert pipeline.matcher_names == ["exact", "sku", "fuzzy"]

        # "kenner" should be caught by exact, not sku or fuzzy
        result = pipeline.match("kenner", sku="tk-kenner-250", name="Kenner Kaffee", resource_type="product")
        assert result is not None
        assert result.match_type == "exact"

    def test_pipeline_falls_through(self, product_handles, collection_handles, sku_map, title_map):
        exact = ExactMatcher(product_handles, collection_handles)
        sku = SKUMatcher(sku_map)

        pipeline = MatcherPipeline([exact, sku])

        # "unknown" won't match exact, but sku "tk-crema-500" will match
        result = pipeline.match("unknown", sku="tk-crema-500", resource_type="product")
        assert result is not None
        assert result.match_type == "sku"

    def test_pipeline_returns_none_if_no_match(self, product_handles, collection_handles):
        exact = ExactMatcher(product_handles, collection_handles)
        pipeline = MatcherPipeline([exact])
        assert pipeline.match("nonexistent", resource_type="product") is None
