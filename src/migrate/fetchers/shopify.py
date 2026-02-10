"""Shopify Admin API fetcher.

Extracted from fetch_shopify_data.py (65 lines) and get_product_skus.py (138 lines).
Credentials come from config. Includes rate limiting and retry logic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()


class ShopifyFetcher:
    """Fetches products, collections, and pages from Shopify Admin API."""

    def __init__(
        self,
        store_url: str,
        access_token: str,
        api_version: str = "2024-10",
        output_dir: str | Path | None = None,
    ) -> None:
        # Normalize store URL
        store_url = store_url.rstrip("/")
        if not store_url.startswith("http"):
            store_url = f"https://{store_url}"
        self.store_url = store_url
        self.api_version = api_version
        self.output_dir = Path(output_dir) if output_dir else None

        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            }
        )

    @property
    def _base(self) -> str:
        return f"{self.store_url}/admin/api/{self.api_version}"

    def _get(self, endpoint: str, params: dict | None = None) -> requests.Response:
        """Authenticated GET with rate-limit retry."""
        url = f"{self._base}/{endpoint}"
        response = self.session.get(url, params=params, timeout=30)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 2))
            console.print(f"  [yellow]Rate limited, waiting {retry_after}s...[/yellow]")
            time.sleep(retry_after)
            return self._get(endpoint, params)
        response.raise_for_status()
        return response

    def _get_paginated(self, endpoint: str, key: str) -> list[dict]:
        """Fetch all pages using Link header pagination."""
        all_items: list[dict] = []
        url: str | None = f"{self._base}/{endpoint}?limit=250"

        while url:
            response = self.session.get(url, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 2))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            all_items.extend(response.json().get(key, []))

            # Follow pagination
            url = None
            link_header = response.headers.get("Link", "")
            if link_header:
                for part in link_header.split(","):
                    if 'rel="next"' in part:
                        url = part.split(";")[0].strip("<> ")
                        break

        return all_items

    # ── Fetchers ─────────────────────────────────────────────

    def fetch_products(self) -> list[dict[str, Any]]:
        """Fetch all products with pagination."""
        products = self._get_paginated("products.json", "products")
        console.print(f"  Shopify: fetched {len(products)} products")
        return products

    def fetch_collections(self) -> list[dict[str, Any]]:
        """Fetch all collections (smart + custom)."""
        all_collections: list[dict] = []
        for coll_type in ["smart_collections", "custom_collections"]:
            resp = self._get(f"{coll_type}.json", {"limit": 250})
            items = resp.json().get(coll_type, [])
            for c in items:
                c["collection_type"] = coll_type.replace("_collections", "")
            all_collections.extend(items)
        console.print(f"  Shopify: fetched {len(all_collections)} collections")
        return all_collections

    def fetch_pages(self) -> list[dict[str, Any]]:
        """Fetch all pages."""
        resp = self._get("pages.json", {"limit": 250})
        pages = resp.json().get("pages", [])
        console.print(f"  Shopify: fetched {len(pages)} pages")
        return pages

    def fetch_all(self) -> FetchResult:
        """Fetch everything and optionally save to disk."""
        console.print("[bold]Fetching Shopify data...[/bold]")
        products = self.fetch_products()
        collections = self.fetch_collections()
        pages = self.fetch_pages()

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in [
                ("products.json", products),
                ("collections.json", collections),
                ("pages.json", pages),
            ]:
                with open(self.output_dir / name, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

        return FetchResult(products=products, collections=collections, pages=pages)
