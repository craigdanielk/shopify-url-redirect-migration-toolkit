"""Configuration model for URL Migration Toolkit.

Loads and validates config.yaml using Pydantic, with environment variable interpolation.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


# ── Sub-models ───────────────────────────────────────────────


class ProjectConfig(BaseModel):
    name: str = "migration"
    description: str = ""


class SourceApiConfig(BaseModel):
    base_url: str = ""
    consumer_key: str = ""
    consumer_secret: str = ""
    access_token: str = ""
    access_token_secret: str = ""


class SourceConfig(BaseModel):
    platform: str = "magento"
    domains: list[str] = Field(default_factory=list)
    api: SourceApiConfig = Field(default_factory=SourceApiConfig)
    csv_file: str = ""
    csv_columns: dict[str, str] = Field(default_factory=dict)


class TargetApiConfig(BaseModel):
    store_url: str = ""
    access_token: str = ""
    api_version: str = "2024-10"


class TargetConfig(BaseModel):
    platform: str = "shopify"
    domain: str = ""
    api: TargetApiConfig = Field(default_factory=TargetApiConfig)


class NormalizerConfig(BaseModel):
    strip_extensions: list[str] = Field(default_factory=lambda: [".html", ".htm", ".php"])
    strip_params: list[str] = Field(
        default_factory=lambda: [
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "gclid",
            "fbclid",
        ]
    )
    trailing_slash: str = "strip"  # strip | add | preserve
    lowercase: bool = True


class SlugTransform(BaseModel):
    from_: str = Field(alias="from", default="")
    to: str = ""


class PatternRule(BaseModel):
    match: str
    action: str  # lookup_by_id | redirect | gone
    target: str = ""
    target_type: str = ""  # product | collection | page


class MatchersConfig(BaseModel):
    pipeline: list[str] = Field(
        default_factory=lambda: ["exact", "sku", "fuzzy", "partial", "pattern"]
    )
    fuzzy_threshold: float = 0.85
    slug_transforms: list[SlugTransform] = Field(default_factory=list)
    patterns: list[PatternRule] = Field(default_factory=list)


class RedirectsConfig(BaseModel):
    default_type: int = 301
    max_per_batch: int = 10000


class OutputConfig(BaseModel):
    directory: str = "output"
    csv_columns: dict[str, str] = Field(
        default_factory=lambda: {"source": "Redirect from", "target": "Redirect to"}
    )


class ValidationConfig(BaseModel):
    request_timeout: int = 15
    rate_limit_delay: float = 0.3
    max_chain_depth: int = 10
    old_domains: list[str] = Field(default_factory=list)


# ── Root Config ──────────────────────────────────────────────


class MigrationConfig(BaseModel):
    """Root configuration model for a URL migration project."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    normalizer: NormalizerConfig = Field(default_factory=NormalizerConfig)
    matchers: MatchersConfig = Field(default_factory=MatchersConfig)
    page_mappings: dict[str, str] = Field(default_factory=dict)
    redirects: RedirectsConfig = Field(default_factory=RedirectsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @model_validator(mode="before")
    @classmethod
    def interpolate_env_vars(cls, data: Any) -> Any:
        """Replace ${VAR} placeholders with environment variable values."""
        if isinstance(data, dict):
            return {k: cls.interpolate_env_vars(v) for k, v in data.items()}
        if isinstance(data, list):
            return [cls.interpolate_env_vars(item) for item in data]
        if isinstance(data, str):
            return _expand_env(data)
        return data


def _expand_env(value: str) -> str:
    """Expand ${VAR} references in a string using os.environ."""
    pattern = re.compile(r"\$\{(\w+)\}")

    def _replacer(m: re.Match) -> str:
        return os.environ.get(m.group(1), m.group(0))

    return pattern.sub(_replacer, value)


def load_config(path: str | Path) -> MigrationConfig:
    """Load and validate a migration config from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return MigrationConfig(**raw)
