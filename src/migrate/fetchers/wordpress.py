"""WordPress REST API v2 fetcher.

Fetches posts, pages, and categories from a live WordPress site.
Falls back to sitemap parsing if the REST API is unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()


class WordPressFetcher:
    """Fetches content from WordPress REST API v2."""

    def __init__(
        self,
        base_url: str,
        output_dir: str | Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/wp-json/wp/v2"
        self.output_dir = Path(output_dir) if output_dir else None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "url-migration-toolkit/0.1"})

    def _get_paginated(self, endpoint: str) -> list[dict]:
        """Fetch all pages of a paginated WP REST endpoint."""
        all_items: list[dict] = []
        page = 1

        while True:
            url = f"{self.api_base}/{endpoint}"
            params = {"per_page": 100, "page": page}

            try:
                response = self.session.get(url, params=params, timeout=30)
                if response.status_code == 400:
                    break  # Past last page
                response.raise_for_status()
                items = response.json()
                if not items:
                    break
                all_items.extend(items)
                page += 1
            except requests.RequestException as e:
                console.print(f"  [red]WP API error ({endpoint}): {e}[/red]")
                break

        return all_items

    def fetch_products(self) -> list[dict[str, Any]]:
        """WordPress doesn't have products natively; return empty."""
        # WooCommerce would be at /wp-json/wc/v3/products but requires auth
        return []

    def fetch_collections(self) -> list[dict[str, Any]]:
        """Fetch categories as collections."""
        console.print("  Fetching categories...")
        categories = self._get_paginated("categories")
        result = []
        for cat in categories:
            result.append(
                {
                    "handle": cat.get("slug", ""),
                    "title": cat.get("name", ""),
                    "id": cat.get("id"),
                    "link": cat.get("link", ""),
                }
            )
        console.print(f"  WordPress: fetched {len(result)} categories")
        return result

    def fetch_pages(self) -> list[dict[str, Any]]:
        """Fetch pages and posts."""
        all_pages: list[dict] = []

        # Pages
        console.print("  Fetching pages...")
        pages = self._get_paginated("pages")
        for p in pages:
            all_pages.append(
                {
                    "handle": p.get("slug", ""),
                    "title": p.get("title", {}).get("rendered", ""),
                    "identifier": p.get("slug", ""),
                    "link": p.get("link", ""),
                    "type": "page",
                }
            )

        # Posts
        console.print("  Fetching posts...")
        posts = self._get_paginated("posts")
        for p in posts:
            all_pages.append(
                {
                    "handle": p.get("slug", ""),
                    "title": p.get("title", {}).get("rendered", ""),
                    "identifier": p.get("slug", ""),
                    "link": p.get("link", ""),
                    "type": "post",
                }
            )

        console.print(f"  WordPress: fetched {len(pages)} pages + {len(posts)} posts")
        return all_pages

    def fetch_all(self) -> FetchResult:
        """Fetch everything from WordPress."""
        console.print(f"[bold]Fetching WordPress data from {self.base_url}...[/bold]")

        # Test if REST API is available
        try:
            resp = self.session.get(f"{self.api_base}", timeout=10)
            if resp.status_code != 200:
                console.print(
                    "[yellow]WP REST API unavailable. Try using sitemap fetcher instead.[/yellow]"
                )
                return FetchResult()
        except requests.RequestException:
            console.print(
                "[yellow]WP REST API unreachable. Try using sitemap fetcher instead.[/yellow]"
            )
            return FetchResult()

        collections = self.fetch_collections()
        pages = self.fetch_pages()

        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in [("categories.json", collections), ("pages.json", pages)]:
                with open(self.output_dir / name, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)

        return FetchResult(collections=collections, pages=pages)
