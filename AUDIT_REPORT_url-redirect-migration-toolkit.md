# AUDIT REPORT: Shopify URL Redirect Migration Toolkit

**Audit Date:** 2026-02-12
**Auditor:** System Auditor (automated)
**Repo:** `shopify-url-redirect-migration-toolkit/`
**Version:** 0.1.0
**Method:** Full source, test, and config file read — every file verified against actual code.

---

## 1. Executive Summary

A well-structured, config-driven Python CLI for CMS-to-Shopify URL redirect mapping. The architecture is clean with proper separation of concerns (fetchers, matchers, validators, uploaders) using protocol-based abstractions. The codebase is **production-ready for Magento, CSV, and WordPress-to-Shopify migrations** with strong validation and rollback support. Key gaps: `pandas` is a declared dependency but never imported, the `uploaders/__init__.py` is a no-export stub, and test coverage for fetchers (Magento, WordPress, CSV, Shopify) is absent. No hardcoded client strings exist in `src/` (only in docstring examples and tests).

---

## 2. Component Status Table

| Component | Status | Evidence |
|---|---|---|
| **CLI (`cli.py`)** | READY | 10 commands implemented: `init`, `discover`, `fetch`, `map`, `upload`, `verify`, `rollback`, `pipeline`, `validate` (with 5 sub-commands). Lines 1-407. |
| **Config (`config.py`)** | READY | Full Pydantic v2 model with 12 sub-models, env var interpolation via `${VAR}` syntax, YAML loading. Lines 1-187. |
| **Normalizer (`normalizer.py`)** | READY | 6 pure functions: `normalize_url`, `strip_extensions`, `strip_query_params`, `apply_trailing_slash`, `extract_path`, `apply_slug_transforms`, `normalize_path_for_comparison`. Lines 1-150. |
| **Mapper (`mapper.py`)** | READY | Full orchestrator: data loading, lookup table construction, pipeline building, URL mapping, loop detection, multi-market prefix expansion, 4 output files. Lines 1-732. |
| **Scaffold (`scaffold.py`)** | READY | Creates project directory with 7 subdirectories + config template + `.env`. Lines 1-59. |
| **Fetcher: Magento** | READY | OAuth 1.0 HMAC-SHA256, paginated product fetch, category tree, CMS pages, disk persistence. Lines 1-150. |
| **Fetcher: Shopify** | READY | Admin API with rate-limit retry + Link-header pagination, products/collections/pages, disk persistence. Lines 1-134. |
| **Fetcher: CSV Import** | READY | Reads CSV with configurable column names, returns `raw_urls`. Lines 1-64. |
| **Fetcher: WordPress** | READY | WP REST API v2 with pagination, categories, pages + posts, REST availability check with fallback message. Lines 1-145. |
| **Fetcher: Sitemap** | READY | Handles sitemap index + urlset, XML namespace-aware, URL type guessing, deduplication, disk save. Lines 1-176. |
| **Fetcher: Wayback** | READY | CDX API querying (domain + www variant), status/MIME filtering, path dedup, CMS era classification (6 eras), rate limiting. Lines 1-248. |
| **Matcher: Exact** | READY | Products, collections, pages. Normalized slug fallback for collections (strip `-` and `_`). Magento url_key cross-reference. Lines 1-99. |
| **Matcher: SKU** | READY | Direct SKU match + Magento ID/url_key fallback. Product-only. Lines 1-72. |
| **Matcher: Fuzzy** | READY | `SequenceMatcher`-based name similarity, configurable threshold, products + collections. Lines 1-80. |
| **Matcher: Partial** | READY | Substring containment (both directions), parent category fallback for nested paths. Lines 1-76. |
| **Matcher: Pattern** | READY | Regex-driven with 3 actions: `redirect` (with capture group expansion), `lookup_by_id`, `gone`. Lines 1-94. |
| **Matcher: Pipeline** | READY | Ordered cascade, first-match-wins, configurable order via `config.yaml`. Lines 1-47. |
| **Validator: CSV Format** | READY | 8 checks: file exists, columns, blanks, duplicates, URL format, trailing slashes, row count, encoding. Lines 1-203. |
| **Validator: Target Existence** | READY | Fetches Shopify resources via API, validates all target handles exist. Lines 1-160. |
| **Validator: Loop Detector** | READY | Graph-based cycle detection + long chain detection. Pre-upload, no HTTP needed. Lines 1-118. |
| **Validator: Chain Detector** | READY | Live HTTP redirect testing post-upload with chain following, max depth control, rate limiting. Lines 1-177. |
| **Validator: Local Tester** | READY | Generates hosts-file instructions + sample test URLs + manual checklist CSV. Advisory (always returns True). Lines 1-162. |
| **Validator: Post-Upload** | READY | HTTP HEAD sampling verification, report CSV output, pass/fail summary. Lines 1-200. |
| **Uploader: Shopify** | READY | REST API redirect creation, existing-redirect fetching, chain flattening, skip-existing, batch pacing, manifest saving, rollback via manifest. Lines 1-333. |
| **Uploader: `__init__.py`** | STUB | Single docstring line, no exports. Not a blocker. |

---

## 3. Detailed Findings

### A. Functionality Inventory

#### A1. CLI Commands (verified: `cli.py` lines 1-407)

| Command | Description | Implementation |
|---|---|---|
| `init` | Scaffold new project | Calls `scaffold.scaffold_project()` |
| `discover` | Historical URL discovery | WaybackFetcher + SitemapFetcher |
| `fetch` | Fetch source + target data | `MigrationEngine.fetch()` |
| `map` | Run URL mapping engine | `MigrationEngine.run()` |
| `upload` | Push redirects to Shopify API | `ShopifyUploader.upload()` |
| `verify` | Post-upload HTTP verification | `PostUploadVerifier.run()` |
| `rollback` | Delete last upload's redirects | `ShopifyUploader.rollback()` |
| `pipeline` | Full end-to-end (discover→fetch→map→validate→upload→verify) | Orchestrates all steps with `--skip-*` flags |
| `validate` | Run all validation layers | `run_all_validators()` |
| `validate csv` | CSV format check | `CSVFormatValidator.run()` |
| `validate targets` | Target existence check | `TargetExistenceValidator.run()` |
| `validate live` | Live redirect chain test | `ChainDetectorValidator.run()` |
| `validate local` | Local testing instructions | `LocalTesterValidator.run()` |
| `validate post-upload` | Post-upload HTTP verification | `PostUploadVerifier.run()` |

**Note:** README mentions `init → discover → fetch → map → validate → upload → verify` lifecycle. CLI actually implements all of these + `rollback` + `pipeline`. README is accurate.

#### A2. Fetchers (verified: `src/migrate/fetchers/`)

| Fetcher | Platform | What It Fetches |
|---|---|---|
| `MagentoFetcher` | Magento 2 | Products (paginated), category tree, CMS pages via OAuth 1.0 REST API |
| `ShopifyFetcher` | Shopify | Products, smart + custom collections, pages via Admin API with Link-header pagination |
| `CSVImportFetcher` | Any (CSV) | Reads `source_url`, `resource_type`, `name`, `url_key` columns from a CSV file |
| `WordPressFetcher` | WordPress | Categories, pages, posts via WP REST API v2 with pagination. REST availability check. |
| `SitemapFetcher` | Any (XML) | Parses sitemap.xml and sitemap index files, extracts URLs with type guessing |
| `WaybackFetcher` | Any (historical) | Internet Archive CDX API, filters by status/MIME, deduplicates, classifies CMS era |

#### A3. Matchers (verified: `src/migrate/matchers/`)

| Matcher | Strategy | Input | Output |
|---|---|---|---|
| `ExactMatcher` | Exact string equality of url_key vs handle | `url_key`, `product_id`, `resource_type` | `MatchResult` with `/products/{handle}` or `/collections/{handle}` or `/pages/{handle}` |
| `SKUMatcher` | SKU cross-reference (direct + Magento ID/url_key lookup) | `url_key`, `sku`, `product_id` (product only) | `MatchResult` with `/products/{handle}`, confidence 0.95 |
| `FuzzyMatcher` | `SequenceMatcher` ratio against product/collection titles | `name`, `resource_type` | `MatchResult` with confidence = similarity ratio |
| `PartialMatcher` | Substring containment (either direction) + parent fallback | `url_key`, `resource_type` | `MatchResult` with confidence 0.7 |
| `PatternMatcher` | Regex rules with 3 actions: `redirect`, `lookup_by_id`, `gone` | `url_key` (as path) | `MatchResult` with configurable target, supports capture group expansion |
| `MatcherPipeline` | Ordered cascade, returns first match | All matcher inputs | First non-None `MatchResult` |

#### A4. Validators (verified: `src/migrate/validators/`)

| Validator | What It Checks |
|---|---|
| `CSVFormatValidator` | File exists, correct column pairs (4 variants), no blank rows, no duplicate sources, URL format (relative paths), consistent trailing slashes, row count within limit, URL encoding |
| `TargetExistenceValidator` | Fetches live Shopify data, checks every target handle exists in products/collections/pages cache |
| `LoopDetectorValidator` | Graph-based cycle detection on redirect CSV (no HTTP). Finds loops and long chains exceeding `max_chain_depth` |
| `ChainDetectorValidator` | Post-upload live HTTP testing: follows redirect chains, checks final URL matches expected target, rate-limited |
| `LocalTesterValidator` | Generates hosts-file instructions, samples test URLs by category, outputs instructions + manual checklist CSV |
| `PostUploadVerifier` | HTTP HEAD request sampling, verifies 301 status + correct Location header, saves CSV report |

#### A5. Uploader Assessment (verified: `uploaders/shopify.py` lines 1-333)

**Status: FULLY IMPLEMENTED**

- Creates redirects via `POST /admin/api/{version}/redirects.json`
- Rate-limit retry (429 handling with `Retry-After` header)
- Fetches existing redirects for skip-existing and chain flattening
- Chain flattening: resolves A->B + existing B->C to A->C (cycle-safe, max depth 10)
- Batch pacing: configurable `batch_size` and `pause_between_batches`
- Manifest saving: writes `upload_manifest.json` with created IDs for rollback
- Rollback: reads manifest, deletes each redirect by ID
- Handles "path already taken" errors gracefully (adds to `skipped` list)
- Dry run mode: previews without API calls

---

### B. Code Quality

#### B1. Hardcoded Domains/URLs in `src/`

**Result: NEAR-ZERO (acceptable)**

Only 2 occurrences in `src/`, both in docstring comments (not executable code):
- `normalizer.py:4` — `"...scattered across the original migration codebase"` (docstring context)
- `normalizer.py:114` — `"https://example-shop.example/products/example-product -> /products/example-product"` (docstring example)

**Verdict:** These are documentation examples, not functional code. Zero hardcoded domains in executable `src/` logic. **PASS.**

#### B2. Config-Driven Behavior

**Result: YES — config.py fully drives behavior.**

All behavior-controlling values flow from `MigrationConfig`:
- Domains: `source.domains`, `target.domain`
- API credentials: `source.api.*`, `target.api.*`
- Normalization rules: `normalizer.*`
- Matcher pipeline order: `matchers.pipeline`
- Fuzzy threshold: `matchers.fuzzy_threshold`
- Slug transforms: `matchers.slug_transforms`
- Pattern rules: `matchers.patterns`
- Page mappings: `page_mappings`
- Output paths: `output.directory`, `output.csv_columns`
- Upload config: `upload.*`
- Validation config: `validation.*`
- Markets: `markets[*]`
- Discovery: `discover.*`

**Hidden defaults exist but are reasonable:**
- `source.platform` defaults to `"magento"` (config.py:33)
- `target.api.api_version` defaults to `"2024-10"` (config.py:43)
- `normalizer.strip_extensions` defaults to `[".html", ".htm", ".php"]` (config.py:53)
- `normalizer.trailing_slash` defaults to `"strip"` (config.py:65)
- `matchers.pipeline` defaults to `["exact", "sku", "fuzzy", "partial", "pattern"]` (config.py:82-84)
- `upload.batch_size` defaults to `50`, `pause_between_batches` to `2.0` (config.py:112-113)

All defaults are documented in `config.example.yaml`. **PASS.**

#### B3. Protocol Implementation

**BaseFetcher Protocol** (`fetchers/base.py:20-30`):
| Fetcher | `fetch_products` | `fetch_collections` | `fetch_pages` | `fetch_all` |
|---|---|---|---|---|
| MagentoFetcher | YES | YES | YES | YES |
| ShopifyFetcher | YES | YES | YES | YES |
| CSVImportFetcher | YES (returns []) | YES (returns []) | YES (returns []) | YES |
| WordPressFetcher | YES (returns []) | YES | YES | YES |
| SitemapFetcher | YES (returns []) | YES (returns []) | YES (returns []) | YES |
| WaybackFetcher | YES (returns []) | YES (returns []) | YES (returns []) | YES |

**Note:** CSVImportFetcher, SitemapFetcher, and WaybackFetcher return empty lists for `fetch_products/collections/pages` because they use `raw_urls` instead. This is by design — the protocol is satisfied.

**BaseMatcher Protocol** (`matchers/base.py:22-43`):
| Matcher | `name` property | `match()` method |
|---|---|---|
| ExactMatcher | YES (class var) | YES |
| SKUMatcher | YES (class var) | YES |
| FuzzyMatcher | YES (class var) | YES |
| PartialMatcher | YES (class var) | YES |
| PatternMatcher | YES (class var) | YES |

**Verdict:** All subclasses properly implement their respective protocols. **PASS.**

#### B4. TODO/FIXME/HACK Comments

**Result: ZERO.** Grep of entire `src/` directory found no TODO, FIXME, HACK, or XXX comments. **PASS.**

#### B5. Dead Code / Unused Imports

| Finding | Details |
|---|---|
| `pandas` dependency declared but never used | `pyproject.toml:18` lists `pandas>=2.0` as a dependency. **Zero imports of pandas** anywhere in `src/`. Should be removed. |
| `uploaders/__init__.py` is a docstring-only stub | Contains only `"""Redirect upload modules for target platforms."""` — no exports. Minor but inconsistent with `fetchers/__init__.py` and `matchers/__init__.py` which export their base classes. |
| `python-dotenv` dependency declared but never imported | `pyproject.toml:17` lists `python-dotenv>=1.0`. **Zero imports** in `src/`. Config env vars are handled by custom `_expand_env()` in `config.py:167-173`. Should be removed. |
| `re` import in `normalizer.py:9` | Used only by `extract_path()`. Valid. |

---

### C. Test Coverage

#### C1. Test File Analysis

| Test File | What It Tests | What It Misses |
|---|---|---|
| `test_config.py` (104 lines) | Config loading (minimal, example store), defaults, env var interpolation, missing file, empty config | Multi-market config parsing (covered in `test_multi_market.py`), upload config, validation config |
| `test_normalizer.py` (184 lines) | All 6 functions: strip_extensions (8 cases), strip_query_params (6 cases), trailing_slash (5 cases), extract_path (5 cases), normalize_url (3 cases), slug_transforms (2 cases), normalize_path_for_comparison (1 case) | Edge cases for full URLs with query + extension + slash combined |
| `test_matchers.py` (255 lines) | All 5 matchers + pipeline: ExactMatcher (6 cases), SKUMatcher (4 cases), FuzzyMatcher (4 cases), PartialMatcher (3 cases), PatternMatcher (5 cases), Pipeline (3 cases) | PatternMatcher capture group expansion (`\1` replacement), page matching in ExactMatcher |
| `test_mapper.py` (139 lines) | End-to-end mapping, unmapped URL detection, dry-run, loop detection | Multi-domain source URLs, market prefix expansion in output, CMS page mapping via `page_mappings` config |
| `test_validators.py` (145 lines) | CSVFormatValidator (7 cases: valid, missing file, blanks, duplicates, full URLs, empty, wrong columns), LoopDetectorValidator (4 cases: simple loop, no loops, missing file, direct loop) | `TargetExistenceValidator` (requires API mocking), `ChainDetectorValidator` (requires HTTP mocking), `LocalTesterValidator`, `PostUploadVerifier` |
| `test_uploader.py` (96 lines) | CSV loading, dry-run, chain flattening (2 cases: normal + cycle), rollback (no manifest + empty manifest) | Actual API upload (mocked `_create_redirect`), skip-existing logic, manifest saving, pagination of existing redirects |
| `test_sitemap.py` (87 lines) | `_guess_type` (5 cases), URL set parsing, empty sitemap, deduplication | Sitemap index parsing (method exists but not tested with real flow), disk saving |
| `test_wayback.py` (87 lines) | Era classification (6 cases), entry filtering (2 cases), deduplication, root skipping, `fetch_all` CDX call count | Actual CDX response parsing, rate limit handling, disk saving |
| `test_multi_market.py` (94 lines) | Market config parsing, no-markets default, prefix expansion (2 cases: with/without markets) | Market `source_domains` filtering, `target_domain` per-market |

#### C2. Integration vs Unit Tests

- **Unit tests:** ALL 9 test files are unit tests
- **Integration tests:** NONE. No tests actually call external APIs or run the full `pipeline` command.
- The `test_mapper.py` `test_end_to_end_mapping` is the closest to integration — it runs the full mapping pipeline with fixture data on disk.

#### C3. Matchers with NO Test Coverage

**ALL matchers have test coverage** in `test_matchers.py`. Every matcher (exact, sku, fuzzy, partial, pattern, pipeline) has dedicated test cases.

#### C4. Fetchers with NO Test Coverage

| Fetcher | Has Tests? |
|---|---|
| MagentoFetcher | **NO** |
| ShopifyFetcher | **NO** |
| CSVImportFetcher | **NO** |
| WordPressFetcher | **NO** |
| SitemapFetcher | **YES** (`test_sitemap.py`) |
| WaybackFetcher | **YES** (`test_wayback.py`) |

**4 out of 6 fetchers have no test coverage.** MagentoFetcher, ShopifyFetcher, CSVImportFetcher, and WordPressFetcher need mocked tests.

---

### D. Readiness Assessment

#### D1. Can This Run Against a NEW Website Today?

**YES** — with caveats:

1. **CSV import mode** (`platform: csv`): Works immediately. No API needed. Just provide a CSV with source URLs.
2. **WordPress mode** (`platform: wordpress`): Works if the WP REST API is publicly accessible (no auth required for public endpoints).
3. **Magento mode** (`platform: magento`): Works if you have OAuth 1.0 credentials.
4. **Sitemap mode** (`platform: sitemap`): Works immediately with any sitemap URL.
5. **Wayback mode** (`platform: wayback`): Works immediately for URL discovery.

**What would NOT work:**
- A TYPO3 source fetcher is mentioned in README but **does not exist** as a dedicated fetcher. Users would need to use sitemap or wayback discovery + CSV import as a workaround.
- `platform: typo3` is not handled in `mapper.py:_create_source_fetcher()` — it would raise `ValueError("Unsupported source platform: typo3")`.

#### D2. Hard Dependencies

| Dependency | Required For | External? |
|---|---|---|
| Shopify Admin API access token | Target data fetching, upload, target validation | YES — requires Shopify custom app |
| Magento OAuth 1.0 credentials | Source data fetching (Magento only) | YES — requires Magento API access |
| Internet Archive CDX API | Wayback URL discovery | YES — public, free, rate-limited |
| WordPress REST API | WordPress source fetching | YES — public endpoints, no auth for read |
| Python 3.11+ | Runtime | Local |
| `uv` | Package management | Local |

#### D3. Component Readiness Ratings

| Component | Rating | Notes |
|---|---|---|
| CLI | **READY** | Full lifecycle coverage |
| Config | **READY** | Comprehensive Pydantic model |
| Normalizer | **READY** | Well-tested, pure functions |
| Mapper | **READY** | Full orchestration with output |
| Scaffold | **READY** | Creates project structure |
| Fetcher: Magento | **READY** | OAuth 1.0 implemented |
| Fetcher: Shopify | **READY** | Rate-limit + pagination |
| Fetcher: CSV | **READY** | Simple, reliable |
| Fetcher: WordPress | **READY** | REST API v2 + fallback |
| Fetcher: Sitemap | **READY** | Namespace-aware XML |
| Fetcher: Wayback | **READY** | CDX API + era classification |
| Matcher: Exact | **READY** | Multi-resource type |
| Matcher: SKU | **READY** | Cross-reference capable |
| Matcher: Fuzzy | **READY** | Configurable threshold |
| Matcher: Partial | **READY** | Bidirectional + parent fallback |
| Matcher: Pattern | **READY** | Regex with 3 actions |
| Matcher: Pipeline | **READY** | Ordered cascade |
| Validator: CSV Format | **READY** | 8 comprehensive checks |
| Validator: Target Existence | **READY** | Live API validation |
| Validator: Loop Detector | **READY** | Graph-based, pre-upload |
| Validator: Chain Detector | **READY** | Live HTTP testing |
| Validator: Local Tester | **READY** | Advisory output |
| Validator: Post-Upload | **READY** | HTTP HEAD sampling |
| Uploader: Shopify | **READY** | Full CRUD + rollback |
| Test Suite | **PARTIAL** | 4/6 fetchers untested, no integration tests |

#### D4. #1 Blocker for Production Readiness

**Missing fetcher test coverage (4 of 6 fetchers).** The MagentoFetcher (OAuth 1.0 signing), ShopifyFetcher (pagination + rate limiting), CSVImportFetcher, and WordPressFetcher have no tests. A regression in OAuth signing or pagination logic would not be caught. This is the highest-risk gap.

**Secondary:** The `pandas` and `python-dotenv` dependencies are declared but unused, adding unnecessary install size and potential version conflicts.

---

### E. Interface Contract

#### E1. INPUT Format

**Configuration:**
- `config.yaml` — YAML file conforming to `MigrationConfig` Pydantic model
- `.env` — Environment variables referenced via `${VAR}` syntax in config

**Source Data (one of):**
- **CSV file:** Columns `source_url` (required), `resource_type` (optional), `name` (optional), `url_key` (optional). Column names configurable via `source.csv_columns`.
- **Magento API:** OAuth 1.0 credentials in config. Returns products, categories, CMS pages as JSON.
- **WordPress REST API:** Base URL in config. Returns categories, pages, posts as JSON.
- **Sitemap XML:** URL to sitemap.xml. Standard sitemap format (urlset or sitemapindex).
- **Wayback CDX API:** Domain names in `source.domains`. No credentials needed.

**Target Data:**
- **Shopify Admin API:** Store URL + access token in config. Fetches products, collections, pages.

#### E2. OUTPUT Format

All outputs written to `{config.output.directory}/`:

| File | Location | Format | Columns/Fields |
|---|---|---|---|
| Complete mapping | `04_redirect_mapping/complete_mapping.csv` | CSV | `source_url`, `target_url`, `resource_type`, `mapping_status`, `match_type`, `confidence`, `notes` |
| Shopify redirects | `06_output/shopify_redirects_complete.csv` | CSV | `{src_col}`, `{tgt_col}` (default: `Redirect from`, `Redirect to`) — relative paths only |
| Unmapped URLs | `03_mapping_rules/unmapped_urls.csv` | CSV | `source_url`, `resource_type`, `mapping_status`, `notes`, `suggested_action` |
| Duplicates log | `04_redirect_mapping/duplicates_log.csv` | CSV | `target_url`, `source_url_count`, `source_urls` |
| Upload manifest | `upload_manifest.json` | JSON | `timestamp`, `store`, `csv_path`, `created_ids[]`, `skipped_count`, `error_count` |
| Post-upload report | `tests/pre-launch/validation_reports/post_upload_verification.csv` | CSV | `source`, `expected_target`, `status_code`, `location`, `result`, `error` |
| Local test instructions | `tests/pre-launch/validation_reports/local_test_instructions.txt` | Text | Human-readable testing instructions |
| Manual test checklist | `tests/pre-launch/validation_reports/manual_test_checklist.csv` | CSV | `Test #`, `Category`, `Source URL`, `Expected Target`, `Status`, `Notes` |

#### E3. Programmatic API

**YES** — the tool can be called programmatically (not just CLI):

```python
from migrate.config import load_config
from migrate.mapper import MigrationEngine
from migrate.uploaders.shopify import ShopifyUploader
from migrate.validators import run_all_validators

cfg = load_config("config.yaml")
engine = MigrationEngine(cfg)
engine.fetch()
engine.run()
run_all_validators(cfg)
uploader = ShopifyUploader(cfg)
uploader.upload()
```

Key classes for programmatic use:
- `MigrationConfig` — construct directly or via `load_config()`
- `MigrationEngine` — `fetch()`, `run()`
- `ShopifyUploader` — `upload()`, `rollback()`
- `PostUploadVerifier` — `run()`
- Individual fetchers, matchers, validators — all independently instantiable

---

## 4. Critical Issues

| # | Severity | Issue | Impact |
|---|---|---|---|
| 1 | **MEDIUM** | 4/6 fetchers have zero test coverage (Magento, Shopify, CSV, WordPress) | Regression in OAuth signing, pagination, or CSV parsing would not be caught |
| 2 | **LOW** | `pandas>=2.0` declared as dependency but never imported | Unnecessary 30MB+ install, potential version conflicts |
| 3 | **LOW** | `python-dotenv>=1.0` declared as dependency but never imported | Unused dependency; env var expansion handled by custom `_expand_env()` |
| 4 | **LOW** | TYPO3 mentioned in README/CLAUDE.md but no dedicated fetcher exists | Users expecting TYPO3 support would need to use sitemap/wayback + CSV workaround |
| 5 | **INFO** | Client-specific strings in docstrings (`normalizer.py:4,114`) and test fixtures (`test_normalizer.py`, `test_config.py`) | Not functional code, but could confuse future contributors |
| 6 | **INFO** | `uploaders/__init__.py` has no exports (unlike `fetchers/__init__.py` and `matchers/__init__.py`) | Inconsistency, not a bug |

---

## 5. Recommendations (Prioritized)

### Priority 1: Test Coverage (estimated effort: 4-6 hours)
1. Add mocked tests for `MagentoFetcher` — test OAuth header generation, pagination, category tree parsing
2. Add mocked tests for `ShopifyFetcher` — test rate-limit retry, Link-header pagination, collection type tagging
3. Add tests for `CSVImportFetcher` — test column mapping, missing file handling, malformed CSV
4. Add mocked tests for `WordPressFetcher` — test REST API unavailability fallback, pagination, post/page normalization

### Priority 2: Dependency Cleanup (estimated effort: 15 minutes)
5. Remove `pandas>=2.0` from `pyproject.toml` dependencies
6. Remove `python-dotenv>=1.0` from `pyproject.toml` dependencies
7. Run `uv lock` to update lockfile

### Priority 3: Documentation Accuracy (estimated effort: 30 minutes)
8. Clarify TYPO3 support in README: recommend sitemap + wayback discovery as the workaround
9. Sanitize docstring examples in `normalizer.py` to use generic domains (e.g., `example.com`)

### Priority 4: Minor Code Quality (estimated effort: 1 hour)
10. Add exports to `uploaders/__init__.py` to match `fetchers/` and `matchers/` patterns
11. Add a `TYPO3Fetcher` stub that delegates to `SitemapFetcher` for forward compatibility
12. Consider adding `--format json` output option for programmatic consumers

---

## 6. Interface Contract Summary (for Pipeline Integration)

```
SERVICE: url-migration-toolkit
VERSION: 0.1.0
TYPE: CLI + Python library

INPUTS:
  config:    config.yaml (MigrationConfig schema)
  env:       .env file or exported env vars for ${VAR} interpolation
  source:    CSV file OR API credentials (Magento/WordPress/Shopify)
  
OUTPUTS:
  primary:   output/06_output/shopify_redirects_complete.csv
             Columns: "Redirect from" (path), "Redirect to" (path)
  mapping:   output/04_redirect_mapping/complete_mapping.csv
             Columns: source_url, target_url, resource_type, mapping_status, 
                      match_type, confidence, notes
  unmapped:  output/03_mapping_rules/unmapped_urls.csv
  manifest:  output/upload_manifest.json (for rollback)
  
PROGRAMMATIC ENTRY POINTS:
  migrate.config.load_config(path) -> MigrationConfig
  migrate.mapper.MigrationEngine(config).run() -> writes CSV outputs
  migrate.uploaders.shopify.ShopifyUploader(config).upload() -> pushes to Shopify
  migrate.validators.run_all_validators(config) -> bool (pass/fail)
  
EXTERNAL DEPENDENCIES:
  - Shopify Admin REST API (redirects, products, collections, pages)
  - Magento 2 REST API with OAuth 1.0 (optional, source-dependent)
  - WordPress REST API v2 (optional, source-dependent)
  - Internet Archive CDX API (optional, for URL discovery)
  
CLI:
  migrate init --name <project>
  migrate fetch --config <path>
  migrate map --config <path>
  migrate validate --config <path>
  migrate upload --config <path>
  migrate verify --config <path>
  migrate rollback --config <path>
  migrate pipeline --config <path> [--skip-discover] [--skip-upload] [--skip-verify] [--dry-run]
```

---

*End of audit report.*
