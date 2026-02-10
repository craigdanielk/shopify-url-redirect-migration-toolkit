"""Matcher pipeline — runs matchers in configured order, returns first hit.

The pipeline reads matcher names from config and executes them in sequence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from migrate.matchers.base import BaseMatcher, MatchResult

if TYPE_CHECKING:
    pass


class MatcherPipeline:
    """Ordered cascade of matchers. Returns the first successful match."""

    def __init__(self, matchers: list[BaseMatcher]) -> None:
        self._matchers = matchers

    @property
    def matcher_names(self) -> list[str]:
        return [m.name for m in self._matchers]

    def match(
        self,
        url_key: str,
        *,
        product_id: str | None = None,
        sku: str | None = None,
        name: str | None = None,
        resource_type: str = "product",
    ) -> MatchResult | None:
        """Run all matchers in order, returning the first hit."""
        for matcher in self._matchers:
            result = matcher.match(
                url_key,
                product_id=product_id,
                sku=sku,
                name=name,
                resource_type=resource_type,
            )
            if result is not None:
                return result
        return None
