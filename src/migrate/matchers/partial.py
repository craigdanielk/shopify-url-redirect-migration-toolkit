"""Partial / substring matcher — Strategy 4.

Matches when the source url_key is contained within a target handle, or vice-versa.
Extracted from complete_url_mapping.py lines 216-226.
"""

from __future__ import annotations

from migrate.matchers.base import MatchResult


class PartialMatcher:
    """Matches by substring containment between url_key and handle."""

    name = "partial"

    def __init__(
        self,
        product_handles: dict[str, dict],
        collection_handles: dict[str, dict],
    ) -> None:
        self.product_handles = product_handles
        self.collection_handles = collection_handles

    def match(
        self,
        url_key: str,
        *,
        product_id: str | None = None,
        sku: str | None = None,
        name: str | None = None,
        resource_type: str = "product",
    ) -> MatchResult | None:
        if not url_key:
            return None

        key = url_key.lower()

        if resource_type == "product":
            for handle, info in self.product_handles.items():
                if key in handle or handle in key:
                    return MatchResult(
                        handle=info["handle"],
                        match_type="partial",
                        confidence=0.7,
                        target_type="product",
                        target_path=f"/products/{info['handle']}",
                    )

        elif resource_type == "collection":
            slug = key.split("/")[-1] if "/" in key else key
            # Try parent fallback for categories
            for coll_handle, info in self.collection_handles.items():
                if slug in coll_handle or coll_handle in slug:
                    return MatchResult(
                        handle=info["handle"],
                        match_type="partial",
                        confidence=0.7,
                        target_type="collection",
                        target_path=f"/collections/{info['handle']}",
                    )
            # Parent fallback for nested category paths
            if "/" in key:
                parent_slug = key.rsplit("/", 1)[0].split("/")[-1] if "/" in key else key
                if parent_slug in self.collection_handles:
                    info = self.collection_handles[parent_slug]
                    return MatchResult(
                        handle=info["handle"],
                        match_type="parent_fallback",
                        confidence=0.7,
                        target_type="collection",
                        target_path=f"/collections/{info['handle']}",
                    )

        return None
