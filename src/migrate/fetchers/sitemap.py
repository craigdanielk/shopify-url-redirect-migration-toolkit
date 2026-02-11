"""Sitemap XML parser fetcher — extracts URLs from sitemap.xml files.

Handles both sitemap index files (pointing to sub-sitemaps) and direct
URL sitemaps. Works for any CMS that generates standard sitemaps.
"""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from rich.console import Console

from migrate.fetchers.base import FetchResult

console = Console()

# XML namespace for sitemaps
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class SitemapFetcher:
    """Extracts URLs from sitemap.xml or sitemap index files."""

    def __init__(
        self,
        sitemap_url: str,
        output_dir: str | Path | None = None,
    ) -> None:
        self.sitemap_url = sitemap_url
        self.output_dir = Path(output_dir) if output_dir else None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "url-migration-toolkit/0.1"})

    def _fetch_xml(self, url: str) -> ET.Element | None:
        """Fetch and parse an XML document."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return ET.fromstring(response.content)
        except (requests.RequestException, ET.ParseError) as e:
            console.print(f"  [red]Failed to fetch {url}: {e}[/red]")
            return None

    def _parse_sitemap_index(self, root: ET.Element) -> list[str]:
        """Extract sub-sitemap URLs from a sitemap index."""
        urls: list[str] = []
        for sitemap in root.findall("sm:sitemap", SITEMAP_NS):
            loc = sitemap.find("sm:loc", SITEMAP_NS)
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        return urls

    def _parse_urlset(self, root: ET.Element) -> list[dict[str, str]]:
        """Extract URLs from a URL set sitemap."""
        entries: list[dict[str, str]] = []
        for url_elem in root.findall("sm:url", SITEMAP_NS):
            loc = url_elem.find("sm:loc", SITEMAP_NS)
            lastmod = url_elem.find("sm:lastmod", SITEMAP_NS)

            if loc is not None and loc.text:
                url = loc.text.strip()
                parsed = urlparse(url)
                path = parsed.path
                entries.append(
                    {
                        "source_url": url,
                        "path": path,
                        "resource_type": _guess_type(path),
                        "name": "",
                        "url_key": path.strip("/").split("/")[-1] if path.strip("/") else "",
                        "domain": parsed.netloc,
                        "lastmod": lastmod.text.strip()
                        if lastmod is not None and lastmod.text
                        else "",
                    }
                )
        return entries

    def _discover_urls(self) -> list[dict[str, str]]:
        """Fetch sitemap(s) and extract all URLs."""
        root = self._fetch_xml(self.sitemap_url)
        if root is None:
            return []

        # Check if it's a sitemap index
        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        if tag == "sitemapindex":
            console.print("  Found sitemap index, fetching sub-sitemaps...")
            sub_urls = self._parse_sitemap_index(root)
            all_entries: list[dict[str, str]] = []
            for sub_url in sub_urls:
                console.print(f"  Fetching {sub_url}...")
                sub_root = self._fetch_xml(sub_url)
                if sub_root is not None:
                    all_entries.extend(self._parse_urlset(sub_root))
            return all_entries

        elif tag == "urlset":
            return self._parse_urlset(root)

        else:
            console.print(f"  [yellow]Unknown sitemap format: {tag}[/yellow]")
            return []

    # ── Public API ───────────────────────────────────────────

    def fetch_products(self) -> list[dict[str, Any]]:
        return []

    def fetch_collections(self) -> list[dict[str, Any]]:
        return []

    def fetch_pages(self) -> list[dict[str, Any]]:
        return []

    def fetch_all(self) -> FetchResult:
        """Fetch all URLs from the sitemap."""
        console.print(f"[bold]Parsing sitemap: {self.sitemap_url}[/bold]")

        entries = self._discover_urls()
        console.print(f"  Found {len(entries)} URLs")

        # Deduplicate by path
        seen: set[str] = set()
        deduped: list[dict[str, str]] = []
        for entry in entries:
            path = entry["path"].lower().rstrip("/") or "/"
            if path not in seen:
                seen.add(path)
                deduped.append(entry)

        console.print(f"  After deduplication: {len(deduped)}")

        # Save to disk
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            csv_path = self.output_dir / "sitemap_urls.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "source_url",
                        "path",
                        "resource_type",
                        "name",
                        "url_key",
                        "domain",
                        "lastmod",
                    ],
                )
                writer.writeheader()
                writer.writerows(deduped)
            console.print(f"  Saved to {csv_path}")

        return FetchResult(raw_urls=deduped)


def _guess_type(path: str) -> str:
    """Guess resource type from URL path."""
    p = path.lower()
    if "/product" in p or "/catalog/" in p:
        return "product"
    elif "/collection" in p or "/categor" in p:
        return "category"
    elif "/page" in p or "/about" in p or "/contact" in p:
        return "cms_page"
    elif "/blog" in p or "/news" in p or "/article" in p:
        return "blog"
    return "unknown"
