"""CLI entry point for URL Migration Toolkit.

Provides commands for the full migration lifecycle:
  init → discover → fetch → map → validate → upload → verify

Also: rollback, pipeline (end-to-end), and individual validation sub-commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(
    name="migrate",
    help="Config-driven URL migration toolkit for CMS-to-Shopify redirects.",
    no_args_is_help=True,
)
validate_app = typer.Typer(help="Run validation layers.")
app.add_typer(validate_app, name="validate")

console = Console()


# ── Global options ───────────────────────────────────────────

CONFIG_OPTION = typer.Option("config.yaml", "--config", "-c", help="Path to config.yaml")
DRY_RUN_OPTION = typer.Option(False, "--dry-run", help="Preview without writing files")
VERBOSE_OPTION = typer.Option(False, "--verbose", "-v", help="Verbose output")


# ── Commands ─────────────────────────────────────────────────


@app.command()
def init(
    name: str = typer.Option(..., "--name", "-n", help="Project name"),
    output_dir: str = typer.Option(".", "--output", "-o", help="Output directory"),
) -> None:
    """Scaffold a new migration project with directory structure and config template."""
    from migrate.scaffold import scaffold_project

    scaffold_project(name=name, output_dir=output_dir)


@app.command()
def discover(
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Discover historical URLs via Wayback Machine and/or sitemap parsing."""
    from migrate.config import load_config

    cfg = load_config(config)
    output_dir = Path(cfg.output.directory) / "00_source_data" / "discovered"

    results = []

    # Wayback Machine discovery
    if cfg.source.domains:
        from migrate.fetchers.wayback import WaybackFetcher

        fetcher = WaybackFetcher(
            domains=cfg.source.domains,
            output_dir=output_dir,
        )
        result = fetcher.fetch_all()
        results.append(("Wayback Machine", len(result.raw_urls)))

    # Sitemap parsing
    sitemap_url = cfg.discover.sitemap_url
    if sitemap_url:
        from migrate.fetchers.sitemap import SitemapFetcher

        fetcher = SitemapFetcher(
            sitemap_url=sitemap_url,
            output_dir=output_dir,
        )
        result = fetcher.fetch_all()
        results.append(("Sitemap", len(result.raw_urls)))

    if not results:
        console.print(
            "[yellow]No discovery sources configured. "
            "Add source.domains or discover.sitemap_url to config.yaml.[/yellow]"
        )
        raise typer.Exit(code=1)

    console.print("\n[bold]Discovery summary:[/bold]")
    for source, count in results:
        console.print(f"  {source}: {count} URLs")


@app.command()
def fetch(
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Fetch source and target data via platform APIs."""
    from migrate.config import load_config
    from migrate.mapper import MigrationEngine

    cfg = load_config(config)
    engine = MigrationEngine(cfg, dry_run=dry_run, verbose=verbose)
    engine.fetch()


@app.command(name="map")
def map_urls(
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Run URL mapping engine: match source URLs to target equivalents."""
    from migrate.config import load_config
    from migrate.mapper import MigrationEngine

    cfg = load_config(config)
    engine = MigrationEngine(cfg, dry_run=dry_run, verbose=verbose)
    engine.run()


@app.command()
def upload(
    config: Path = CONFIG_OPTION,
    csv_path: Optional[str] = typer.Option(None, "--csv", help="Override redirect CSV path"),
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Upload redirects to Shopify via REST Admin API.

    Reads the validated redirect CSV and creates redirect entries in Shopify.
    Supports chain flattening, skip-existing, and batch pacing.
    """
    from migrate.config import load_config
    from migrate.uploaders.shopify import ShopifyUploader

    cfg = load_config(config)
    uploader = ShopifyUploader(cfg, csv_path=csv_path)
    success = uploader.upload(dry_run=dry_run)
    raise typer.Exit(code=0 if success else 1)


@app.command()
def verify(
    config: Path = CONFIG_OPTION,
    csv_path: Optional[str] = typer.Option(None, "--csv", help="Override redirect CSV path"),
    sample_size: int = typer.Option(50, "--sample", "-s", help="Number of redirects to verify"),
) -> None:
    """Post-upload verification — test redirects via live HTTP requests.

    Samples redirects and verifies 301 status + correct Location header.
    """
    from migrate.config import load_config
    from migrate.validators.post_upload import PostUploadVerifier

    cfg = load_config(config)
    verifier = PostUploadVerifier(cfg, csv_path=csv_path, sample_size=sample_size)
    success = verifier.run()
    raise typer.Exit(code=0 if success else 1)


@app.command()
def rollback(
    config: Path = CONFIG_OPTION,
) -> None:
    """Rollback the last upload — deletes redirects using the upload manifest."""
    from migrate.config import load_config
    from migrate.uploaders.shopify import ShopifyUploader

    cfg = load_config(config)
    uploader = ShopifyUploader(cfg)
    success = uploader.rollback()
    raise typer.Exit(code=0 if success else 1)


@app.command()
def pipeline(
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
    skip_discover: bool = typer.Option(False, "--skip-discover", help="Skip Wayback discovery"),
    skip_upload: bool = typer.Option(False, "--skip-upload", help="Skip Shopify upload"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip post-upload verification"),
) -> None:
    """Run the full migration pipeline end-to-end.

    Executes: discover → fetch → map → validate → upload → verify

    Use --skip-* flags to skip individual steps.
    Use --dry-run to preview the entire pipeline without writing.
    """
    from migrate.config import load_config
    from migrate.mapper import MigrationEngine
    from migrate.validators import run_all_validators

    cfg = load_config(config)
    steps_run = 0
    steps_failed = 0

    # ── Step 1: Discover ──────────────────────────────────
    if not skip_discover and (cfg.source.domains or cfg.discover.sitemap_url):
        console.rule("[bold cyan]Step 1/6: Discover Historical URLs")
        try:
            output_dir = Path(cfg.output.directory) / "00_source_data" / "discovered"
            if cfg.source.domains:
                from migrate.fetchers.wayback import WaybackFetcher

                WaybackFetcher(domains=cfg.source.domains, output_dir=output_dir).fetch_all()
            if cfg.discover.sitemap_url:
                from migrate.fetchers.sitemap import SitemapFetcher

                SitemapFetcher(
                    sitemap_url=cfg.discover.sitemap_url, output_dir=output_dir
                ).fetch_all()
            steps_run += 1
        except Exception as e:
            console.print(f"[yellow]Discovery warning: {e}[/yellow]")
            steps_run += 1  # Non-fatal
    else:
        console.print("[dim]Skipping discovery[/dim]")

    # ── Step 2: Fetch ─────────────────────────────────────
    console.rule("[bold cyan]Step 2/6: Fetch Source + Target Data")
    try:
        engine = MigrationEngine(cfg, dry_run=dry_run, verbose=verbose)
        engine.fetch()
        steps_run += 1
    except Exception as e:
        console.print(f"[red]Fetch failed: {e}[/red]")
        steps_failed += 1

    # ── Step 3: Map ───────────────────────────────────────
    console.rule("[bold cyan]Step 3/6: Map Source → Target URLs")
    try:
        engine = MigrationEngine(cfg, dry_run=dry_run, verbose=verbose)
        engine.run()
        steps_run += 1
    except Exception as e:
        console.print(f"[red]Mapping failed: {e}[/red]")
        steps_failed += 1

    # ── Step 4: Validate ──────────────────────────────────
    console.rule("[bold cyan]Step 4/6: Validate Redirects")
    try:
        passed = run_all_validators(cfg, dry_run=dry_run, verbose=verbose)
        steps_run += 1
        if not passed:
            console.print(
                "[yellow]Validation had warnings. Review output before uploading.[/yellow]"
            )
    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        steps_failed += 1

    # ── Step 5: Upload ────────────────────────────────────
    if not skip_upload:
        console.rule("[bold cyan]Step 5/6: Upload Redirects to Shopify")
        try:
            from migrate.uploaders.shopify import ShopifyUploader

            uploader = ShopifyUploader(cfg)
            success = uploader.upload(dry_run=dry_run)
            steps_run += 1
            if not success:
                steps_failed += 1
        except Exception as e:
            console.print(f"[red]Upload failed: {e}[/red]")
            steps_failed += 1
    else:
        console.print("[dim]Skipping upload[/dim]")

    # ── Step 6: Verify ────────────────────────────────────
    if not skip_upload and not skip_verify:
        console.rule("[bold cyan]Step 6/6: Post-Upload Verification")
        try:
            from migrate.validators.post_upload import PostUploadVerifier

            verifier = PostUploadVerifier(cfg)
            verifier.run()
            steps_run += 1
        except Exception as e:
            console.print(f"[yellow]Verification warning: {e}[/yellow]")
            steps_run += 1
    else:
        console.print("[dim]Skipping verification[/dim]")

    # ── Summary ───────────────────────────────────────────
    console.print()
    if steps_failed == 0:
        console.print(
            Panel(
                f"[green bold]Pipeline complete.[/green bold]\n"
                f"Steps run: {steps_run}, Failed: {steps_failed}",
                title="Migration Pipeline",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[yellow bold]Pipeline finished with errors.[/yellow bold]\n"
                f"Steps run: {steps_run}, Failed: {steps_failed}\n"
                f"Review output above and re-run failed steps individually.",
                title="Migration Pipeline",
                border_style="yellow",
            )
        )

    raise typer.Exit(code=0 if steps_failed == 0 else 1)


# ── Validate sub-commands ────────────────────────────────────


@validate_app.callback(invoke_without_command=True)
def validate_all(
    ctx: typer.Context,
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Run all validation layers in sequence (including post-upload if applicable)."""
    if ctx.invoked_subcommand is not None:
        return
    from migrate.config import load_config
    from migrate.validators import run_all_validators

    cfg = load_config(config)
    run_all_validators(cfg, dry_run=dry_run, verbose=verbose)


@validate_app.command(name="csv")
def validate_csv(
    config: Path = CONFIG_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Validate CSV format for Shopify import."""
    from migrate.config import load_config
    from migrate.validators.csv_format import CSVFormatValidator

    cfg = load_config(config)
    validator = CSVFormatValidator(cfg)
    validator.run()


@validate_app.command(name="targets")
def validate_targets(
    config: Path = CONFIG_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Verify target URLs exist in Shopify."""
    from migrate.config import load_config
    from migrate.validators.target_existence import TargetExistenceValidator

    cfg = load_config(config)
    validator = TargetExistenceValidator(cfg)
    validator.run()


@validate_app.command(name="live")
def validate_live(
    config: Path = CONFIG_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Test live redirects for chains after Shopify import."""
    from migrate.config import load_config
    from migrate.validators.chain_detector import ChainDetectorValidator

    cfg = load_config(config)
    validator = ChainDetectorValidator(cfg)
    validator.run()


@validate_app.command(name="local")
def validate_local(
    config: Path = CONFIG_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Generate local testing instructions (hosts file, manual checks)."""
    from migrate.config import load_config
    from migrate.validators.local_tester import LocalTesterValidator

    cfg = load_config(config)
    validator = LocalTesterValidator(cfg)
    validator.run()


@validate_app.command(name="post-upload")
def validate_post_upload(
    config: Path = CONFIG_OPTION,
    sample_size: int = typer.Option(50, "--sample", "-s", help="Sample size"),
) -> None:
    """Post-upload HTTP verification of live redirects."""
    from migrate.config import load_config
    from migrate.validators.post_upload import PostUploadVerifier

    cfg = load_config(config)
    verifier = PostUploadVerifier(cfg, sample_size=sample_size)
    success = verifier.run()
    raise typer.Exit(code=0 if success else 1)
