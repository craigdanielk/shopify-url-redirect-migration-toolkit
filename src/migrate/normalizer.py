"""URL normalizer — single shared module used by all components.

Consolidates ad-hoc .html stripping, trailing slash handling, query param logic,
and lowercasing that was scattered across the original Turm Kaffee codebase.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

if TYPE_CHECKING:
    from migrate.config import NormalizerConfig


def normalize_url(url: str, config: NormalizerConfig) -> str:
    """Normalize a URL according to config rules.

    Applies in order: lowercase, extension stripping, query param stripping,
    trailing slash policy.
    """
    if not url:
        return ""

    # Lowercase the entire URL if configured
    if config.lowercase:
        url = url.lower()

    # Strip extensions
    url = strip_extensions(url, config.strip_extensions)

    # Strip query params
    url = strip_query_params(url, config.strip_params)

    # Trailing slash policy
    url = apply_trailing_slash(url, config.trailing_slash)

    return url


def strip_extensions(url: str, extensions: list[str]) -> str:
    """Remove file extensions from the path portion of a URL.

    Examples:
        /kaffee/kenner.html  ->  /kaffee/kenner
        /about.php           ->  /about
    """
    if not extensions:
        return url

    parsed = urlparse(url)
    path = parsed.path

    for ext in extensions:
        if path.endswith(ext):
            path = path[: -len(ext)]
            break  # Only strip one extension

    if path != parsed.path:
        return urlunparse(parsed._replace(path=path))
    return url


def strip_query_params(url: str, deny_list: list[str]) -> str:
    """Remove tracking / unwanted query parameters from a URL.

    Strips parameters whose names appear in *deny_list* (case-insensitive).
    Other query parameters are preserved.
    """
    if not deny_list:
        return url

    parsed = urlparse(url)
    if not parsed.query:
        return url

    deny_set = {p.lower() for p in deny_list}
    params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {k: v for k, v in params.items() if k.lower() not in deny_set}

    new_query = urlencode(filtered, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def apply_trailing_slash(url: str, policy: str) -> str:
    """Apply trailing slash policy to the path portion of a URL.

    Policies:
        strip   — remove trailing slash (except for root "/")
        add     — ensure a trailing slash
        preserve — do nothing
    """
    parsed = urlparse(url)
    path = parsed.path

    if policy == "strip":
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
    elif policy == "add":
        if path and not path.endswith("/"):
            path = path + "/"
    # "preserve" — no-op

    if path != parsed.path:
        return urlunparse(parsed._replace(path=path))
    return url


def extract_path(url: str) -> str:
    """Extract the relative path from a full URL.

    Examples:
        https://shop.turmkaffee.ch/products/kenner  ->  /products/kenner
        /products/kenner                             ->  /products/kenner
    """
    if not url:
        return ""

    # Already a relative path
    if url.startswith("/"):
        return url

    # Strip scheme + host
    path = re.sub(r"^https?://[^/]+", "", url)
    return path or "/"


def apply_slug_transforms(slug: str, transforms: list[dict[str, str]]) -> str:
    """Apply configured slug transformation rules.

    Used for language-specific transformations like German umlauts:
        ae -> a, oe -> o, ue -> u
    """
    for t in transforms:
        from_str = t.get("from", t.get("from_", ""))
        to_str = t.get("to", "")
        if from_str:
            slug = slug.replace(from_str, to_str)
    return slug


def normalize_path_for_comparison(url: str, config: NormalizerConfig) -> str:
    """Extract and normalize just the path for matching purposes.

    Combines extract_path + normalize_url for a clean comparable path.
    """
    path = extract_path(url)
    return normalize_url(path, config)
