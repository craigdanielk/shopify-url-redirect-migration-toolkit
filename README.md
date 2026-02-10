# URL Migration Toolkit

Config-driven CLI tool for mapping URLs between CMS platforms (Magento, WordPress, TYPO3) and Shopify, generating redirect CSVs for zero-downtime domain migrations.

## Quick Start

```bash
# Install
uv sync

# Create a new migration project
uv run migrate init --name my-migration

# Edit config.yaml with your source/target details, then:
uv run migrate fetch            # Pull data from source + target APIs
uv run migrate map              # Generate redirect mappings
uv run migrate validate         # Validate before upload
```

## Features

- **Multi-strategy matching**: exact handle, SKU, fuzzy name (SequenceMatcher), partial substring, regex pattern rules
- **Config-driven**: domains, slug transforms, page mappings, matcher order — all in `config.yaml`
- **4-layer validation**: CSV format, target existence, redirect chains, local testing
- **Platform-agnostic fetchers**: Magento (OAuth 1.0), Shopify (Admin API), plain CSV import
- **Loop detection**: graph-based cycle detection on redirect maps before upload

## Installation

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/r17-ventures/url-migration-toolkit.git
cd url-migration-toolkit
uv sync
```

## Usage

### 1. Scaffold a project

```bash
uv run migrate init --name turm-kaffee
```

Creates a directory with standard subdirectories and a `config.yaml` template.

### 2. Configure

Edit `config.yaml` — see `config.example.yaml` for full reference.

### 3. Fetch data

```bash
uv run migrate fetch --config config.yaml
```

### 4. Map URLs

```bash
uv run migrate map --config config.yaml
```

### 5. Validate

```bash
uv run migrate validate --config config.yaml     # All layers
uv run migrate validate csv                       # CSV format only
uv run migrate validate targets                   # Target existence only
uv run migrate validate live                      # Live redirect chains
uv run migrate validate local                     # Local testing guide
```

## Config Reference

See [`config.example.yaml`](config.example.yaml) for all available options.

## Development

```bash
uv sync --all-extras
uv run pytest tests/ --cov=migrate
uv run ruff check src/
```

## License

MIT
