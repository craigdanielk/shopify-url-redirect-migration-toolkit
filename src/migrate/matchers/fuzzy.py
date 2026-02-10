"""Fuzzy name matcher — Strategy 3.

Uses SequenceMatcher to find the best fuzzy match by product/collection name.
Extracted from complete_url_mapping.py lines 198-214.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from migrate.matchers.base import MatchResult


class FuzzyMatcher:
    """Matches source URLs to targets by fuzzy name similarity."""

    name = "fuzzy"

    def __init__(
        self,
        title_to_handle: dict[str, str],
        collection_title_to_handle: dict[str, str] | None = None,
        threshold: float = 0.85,
    ) -> None:
        self.title_to_handle = title_to_handle  # title_lower -> handle
        self.collection_title_to_handle = collection_title_to_handle or {}
        self.threshold = threshold

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Calculate string similarity ratio (0.0 – 1.0)."""
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    def match(
        self,
        url_key: str,
        *,
        product_id: str | None = None,
        sku: str | None = None,
        name: str | None = None,
        resource_type: str = "product",
    ) -> MatchResult | None:
        if not name:
            return None

        name_lower = name.lower()

        if resource_type == "product":
            lookup = self.title_to_handle
            target_type = "product"
            prefix = "/products"
        elif resource_type == "collection":
            lookup = self.collection_title_to_handle
            target_type = "collection"
            prefix = "/collections"
        else:
            return None

        best_handle: str | None = None
        best_score = 0.0

        for title, handle in lookup.items():
            score = self._similarity(name_lower, title)
            if score > best_score and score >= self.threshold:
                best_score = score
                best_handle = handle

        if best_handle:
            return MatchResult(
                handle=best_handle,
                match_type="fuzzy_name",
                confidence=best_score,
                target_type=target_type,
                target_path=f"{prefix}/{best_handle}",
            )

        return None
