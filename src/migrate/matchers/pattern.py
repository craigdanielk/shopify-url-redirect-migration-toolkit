"""Regex pattern matcher — Strategy 5 (NEW).

Config-driven regex rules for URL patterns that need special handling.
This is a new component not present in the original codebase.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from migrate.matchers.base import MatchResult

if TYPE_CHECKING:
    from migrate.config import PatternRule


class PatternMatcher:
    """Matches URLs against configured regex patterns."""

    name = "pattern"

    def __init__(self, patterns: list[PatternRule]) -> None:
        self.rules: list[tuple[re.Pattern, PatternRule]] = []
        for rule in patterns:
            try:
                compiled = re.compile(rule.match)
                self.rules.append((compiled, rule))
            except re.error:
                pass  # Skip invalid patterns

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

        # Ensure we're matching against the path (with leading /)
        path = url_key if url_key.startswith("/") else f"/{url_key}"

        for regex, rule in self.rules:
            m = regex.search(path)
            if not m:
                continue

            if rule.action == "redirect":
                # Static redirect to a fixed target
                target = rule.target
                # Expand capture group references
                for i, group in enumerate(m.groups(), 1):
                    if group is not None:
                        target = target.replace(f"\\{i}", group)

                return MatchResult(
                    handle="",
                    match_type="pattern",
                    confidence=0.9,
                    target_type=rule.target_type or "page",
                    target_path=target,
                    notes=f"Pattern: {rule.match}",
                )

            elif rule.action == "lookup_by_id":
                # Extract ID from capture group and return for downstream lookup
                captured_id = m.group(1) if m.lastindex and m.lastindex >= 1 else None
                if captured_id:
                    return MatchResult(
                        handle=captured_id,
                        match_type="pattern_id_lookup",
                        confidence=0.85,
                        target_type=rule.target_type or "product",
                        target_path="",  # Will be resolved by mapper
                        notes=f"Pattern ID: {captured_id}",
                    )

            elif rule.action == "gone":
                # 410 Gone — resource intentionally removed
                return MatchResult(
                    handle="",
                    match_type="pattern_gone",
                    confidence=1.0,
                    target_type="gone",
                    target_path="",
                    notes=f"410 Gone: {rule.match}",
                )

        return None
