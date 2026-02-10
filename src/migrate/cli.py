"""CLI entry point for URL Migration Toolkit.

Commands are wired up progressively as modules are built.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

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


# ── Validate sub-commands ────────────────────────────────────


@validate_app.callback(invoke_without_command=True)
def validate_all(
    ctx: typer.Context,
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
    verbose: bool = VERBOSE_OPTION,
) -> None:
    """Run all 4 validation layers in sequence."""
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
    """Layer 2: Validate CSV format for Shopify import."""
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
    """Layer 1: Verify target URLs exist in Shopify."""
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
    """Layer 3: Test live redirects after Shopify import."""
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
    """Layer 4: Generate local testing instructions."""
    from migrate.config import load_config
    from migrate.validators.local_tester import LocalTesterValidator

    cfg = load_config(config)
    validator = LocalTesterValidator(cfg)
    validator.run()


# ── Placeholder for future upload command ────────────────────


@app.command()
def upload(
    config: Path = CONFIG_OPTION,
    dry_run: bool = DRY_RUN_OPTION,
) -> None:
    """Upload redirects to Shopify via Bulk Operations API (future)."""
    console.print("[yellow]Upload command is planned for a future release.[/yellow]")
    raise typer.Exit(code=0)
