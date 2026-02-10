"""Exact handle matcher — Strategy 1.

Matches when the source url_key exactly equals a target handle.
Extracted from complete_url_mapping.py lines 165-170.
"""

from __future__ import annotations

from migrate.matchers.base import MatchResult


class ExactMatcher:
    """Matches source url_key to target handle by exact string equality."""

    name = "exact"

    def __init__(
        self,
        product_handles: dict[str, dict],
        collection_handles: dict[str, dict],
        page_handles: dict[str, dict] | None = None,
        magento_urlkey_map: dict[str, dict] | None = None,
    ) -> None:
        self.product_handles = product_handles  # handle_lower -> {handle, title}
        self.collection_handles = collection_handles
        self.page_handles = page_handles or {}
        self.magento_urlkey_map = magento_urlkey_map or {}

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

        # For products: check product handles
        if resource_type == "product":
            if key in self.product_handles:
                return MatchResult(
                    handle=self.product_handles[key]["handle"],
                    match_type="exact",
                    confidence=1.0,
                    target_type="product",
                    target_path=f"/products/{self.product_handles[key]['handle']}",
                )
            # Also try url_key from magento product map
            if product_id and product_id in self.magento_urlkey_map:
                mag_urlkey = self.magento_urlkey_map[product_id].get("url_key", "").lower()
                if mag_urlkey and mag_urlkey in self.product_handles:
                    return MatchResult(
                        handle=self.product_handles[mag_urlkey]["handle"],
                        match_type="exact_urlkey",
                        confidence=1.0,
                        target_type="product",
                        target_path=f"/products/{self.product_handles[mag_urlkey]['handle']}",
                    )

        # For collections: check collection handles
        elif resource_type == "collection":
            slug = key.split("/")[-1] if "/" in key else key
            if slug in self.collection_handles:
                return MatchResult(
                    handle=self.collection_handles[slug]["handle"],
                    match_type="exact",
                    confidence=1.0,
                    target_type="collection",
                    target_path=f"/collections/{self.collection_handles[slug]['handle']}",
                )
            # Try normalized slug
            normalized = slug.replace("-", "").replace("_", "")
            for coll_handle, info in self.collection_handles.items():
                if coll_handle.replace("-", "").replace("_", "") == normalized:
                    return MatchResult(
                        handle=info["handle"],
                        match_type="normalized",
                        confidence=0.95,
                        target_type="collection",
                        target_path=f"/collections/{info['handle']}",
                    )

        # For pages: check page handles
        elif resource_type == "page":
            if key in self.page_handles:
                return MatchResult(
                    handle=self.page_handles[key]["handle"],
                    match_type="exact",
                    confidence=1.0,
                    target_type="page",
                    target_path=f"/pages/{self.page_handles[key]['handle']}",
                )

        return None
