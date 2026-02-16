# URL Migration Toolkit

## What This Is

A config-driven Python CLI tool that maps URLs from a source CMS (Magento, WordPress, etc.) to a target platform (Shopify) and generates redirect CSVs. Extracted from a working Magento-to-Shopify migration (~2,855 lines across 13 scripts).

## Architecture

```
src/migrate/
├── cli.py           # Typer CLI: init, fetch, map, validate, upload
├── config.py        # Pydantic model loading config.yaml
├── normalizer.py    # URL normalization (extensions, slashes, params)
├── mapper.py        # Core orchestrator: fetcher + normalizer + matchers → output
├── matchers/        # 6-strategy matching cascade (exact, sku, fuzzy, partial, pattern, pipeline)
├── fetchers/        # Data fetching (magento, shopify, csv_import)
└── validators/      # 4-layer validation (csv_format, target_existence, chain_detector, local_tester)
```

## Key Design Decisions

- **Config-driven**: All client-specific values (domains, slugs, page mappings, patterns) live in `config.yaml`, not code.
- **Protocol-based**: Matchers and fetchers implement protocols (`BaseMatcher`, `BaseFetcher`) for extensibility.
- **Pipeline ordering**: Matcher cascade order is configurable via `config.yaml`.
- **Zero hardcoded domains**: The `src/` directory contains no client-specific strings.

## Commands

```bash
uv run migrate --help           # Show all commands
uv run migrate init --name X    # Scaffold a new migration project
uv run migrate fetch            # Fetch source + target data via APIs
uv run migrate map              # Run URL mapping engine
uv run migrate validate         # Run all 4 validation layers
uv run migrate validate csv     # Layer 2 only: CSV format check
uv run pytest tests/ --cov      # Run tests
```

## Tech Stack

- Python 3.11+, uv for package management
- typer + rich for CLI
- pydantic for config validation
- PyYAML for config files
- requests for HTTP

## Tests

Run: `uv run pytest tests/ --cov=migrate`
Target: 70%+ coverage on core modules (normalizer, matchers, mapper)
