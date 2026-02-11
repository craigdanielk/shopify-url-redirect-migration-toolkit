"""Base types for the matcher system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class MatchResult:
    """Result returned by a matcher when a match is found."""

    handle: str
    match_type: str  # exact, sku, fuzzy_name, partial, pattern, normalized, parent_fallback
    confidence: float  # 0.0 – 1.0
    target_type: str = "product"  # product | collection | page
    target_path: str = ""  # e.g. /products/kenner
    notes: str = ""


@runtime_checkable
class BaseMatcher(Protocol):
    """Protocol that all matchers must implement."""

    @property
    def name(self) -> str:
        """Short identifier for this matcher (e.g. 'exact', 'sku')."""
        ...

    def match(
        self,
        url_key: str,
        *,
        product_id: str | None = None,
        sku: str | None = None,
        name: str | None = None,
        resource_type: str = "product",
    ) -> MatchResult | None:
        """Attempt to match a source URL key to a target resource.

        Returns a MatchResult on success, or None if no match is found.
        """
        ...
