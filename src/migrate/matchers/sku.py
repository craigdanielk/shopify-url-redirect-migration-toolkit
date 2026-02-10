"""SKU-based matcher — Strategy 2.

Matches when a Magento product's SKU matches a Shopify variant SKU.
Extracted from complete_url_mapping.py lines 189-196.
"""

from __future__ import annotations

from migrate.matchers.base import MatchResult


class SKUMatcher:
    """Matches source products to target products by SKU."""

    name = "sku"

    def __init__(
        self,
        sku_to_handle: dict[str, str],
        magento_urlkey_map: dict[str, dict] | None = None,
        magento_id_map: dict[str, dict] | None = None,
    ) -> None:
        self.sku_to_handle = sku_to_handle  # sku_lower -> handle
        self.magento_urlkey_map = magento_urlkey_map or {}
        self.magento_id_map = magento_id_map or {}

    def match(
        self,
        url_key: str,
        *,
        product_id: str | None = None,
        sku: str | None = None,
        name: str | None = None,
        resource_type: str = "product",
    ) -> MatchResult | None:
        if resource_type != "product":
            return None

        # Direct SKU if provided
        if sku:
            sku_lower = sku.lower()
            if sku_lower in self.sku_to_handle:
                handle = self.sku_to_handle[sku_lower]
                return MatchResult(
                    handle=handle,
                    match_type="sku",
                    confidence=0.95,
                    target_type="product",
                    target_path=f"/products/{handle}",
                )

        # Try to find SKU from Magento product data
        mag_product = None
        if product_id and product_id in self.magento_id_map:
            mag_product = self.magento_id_map[product_id]
        elif url_key and url_key.lower() in self.magento_urlkey_map:
            mag_product = self.magento_urlkey_map[url_key.lower()]

        if mag_product:
            mag_sku = mag_product.get("sku", "").lower()
            if mag_sku and mag_sku in self.sku_to_handle:
                handle = self.sku_to_handle[mag_sku]
                return MatchResult(
                    handle=handle,
                    match_type="sku",
                    confidence=0.95,
                    target_type="product",
                    target_path=f"/products/{handle}",
                )

        return None
