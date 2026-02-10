"""Magento REST API fetcher with OAuth 1.0 authentication.

Extracted from fetch_magento_data.py (100 lines) and get_product_skus.py (138 lines).
All credentials come from config, not hardcoded env vars.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()


class MagentoFetcher:
    """Fetches products, categories, and CMS pages from Magento 2 REST API."""

    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
        output_dir: str | Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.output_dir = Path(output_dir) if output_dir else None

    # ── OAuth 1.0 ────────────────────────────────────────────

    def _oauth_header(self, method: str, url: str, query_params: dict | None = None) -> str:
        oauth_params = {
            "oauth_consumer_key": self.consumer_key,
            "oauth_token": self.access_token,
            "oauth_signature_method": "HMAC-SHA256",
            "oauth_timestamp": str(int(time.time())),
            "oauth_nonce": uuid.uuid4().hex,
            "oauth_version": "1.0",
        }
        all_params = {**oauth_params, **(query_params or {})}
        sorted_params = sorted(all_params.items())
        param_string = "&".join(
            f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
            for k, v in sorted_params
        )
        base_string = (
            f"{method}"
            f"&{urllib.parse.quote(url, safe='')}"
            f"&{urllib.parse.quote(param_string, safe='')}"
        )
        signing_key = (
            f"{urllib.parse.quote(self.consumer_secret, safe='')}"
            f"&{urllib.parse.quote(self.access_token_secret, safe='')}"
        )
        signature = base64.b64encode(
            hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha256).digest()
        ).decode()
        oauth_params["oauth_signature"] = signature
        return "OAuth " + ", ".join(
            f'{k}="{urllib.parse.quote(str(v), safe="")}"' for k, v in oauth_params.items()
        )

    def _get(self, endpoint: str, params: dict | None = None) -> Any:
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "Authorization": self._oauth_header("GET", url, params),
            "Content-Type": "application/json",
        }
        if params:
            full_url = f"{url}?{urllib.parse.urlencode(params)}"
        else:
            full_url = url
        response = requests.get(full_url, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    # ── Fetchers ─────────────────────────────────────────────

    def fetch_products(self) -> list[dict[str, Any]]:
        """Fetch all products with pagination."""
        all_products: list[dict] = []
        page = 1
        while True:
            params = {
                "searchCriteria[pageSize]": "100",
                "searchCriteria[currentPage]": str(page),
            }
            data = self._get("products", params)
            items = data.get("items", [])
            all_products.extend(items)
            if len(all_products) >= data.get("total_count", 0) or not items:
                break
            page += 1
        console.print(f"  Magento: fetched {len(all_products)} products")
        return all_products

    def fetch_collections(self) -> list[dict[str, Any]]:
        """Fetch category tree (Magento calls them categories)."""
        data = self._get("categories")
        console.print("  Magento: fetched category tree")
        return [data] if isinstance(data, dict) else data

    def fetch_pages(self) -> list[dict[str, Any]]:
        """Fetch CMS pages."""
        params = {"searchCriteria[pageSize]": "100"}
        data = self._get("cmsPage/search", params)
        pages = data.get("items", [])
        console.print(f"  Magento: fetched {len(pages)} CMS pages")
        return pages

    def fetch_all(self) -> FetchResult:
        """Fetch everything and optionally save to disk."""
        console.print("[bold]Fetching Magento data...[/bold]")
        products = self.fetch_products()
        categories = self.fetch_collections()
        pages = self.fetch_pages()

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in [
                ("products.json", products),
                ("categories.json", categories[0] if categories else {}),
                ("cms_pages.json", pages),
            ]:
                with open(self.output_dir / name, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

        return FetchResult(
            products=products,
            categories=categories[0] if categories else {},
            pages=pages,
        )
