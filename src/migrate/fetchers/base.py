"""Base types for the fetcher system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class FetchResult:
    """Normalized result from any fetcher."""

    products: list[dict[str, Any]] = field(default_factory=list)
    collections: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    categories: dict[str, Any] | list[dict[str, Any]] = field(default_factory=dict)
    raw_urls: list[dict[str, str]] = field(default_factory=list)  # For CSV import


@runtime_checkable
class BaseFetcher(Protocol):
    """Protocol that all fetchers must implement."""

    def fetch_products(self) -> list[dict[str, Any]]: ...

    def fetch_collections(self) -> list[dict[str, Any]]: ...

    def fetch_pages(self) -> list[dict[str, Any]]: ...

    def fetch_all(self) -> FetchResult: ...
