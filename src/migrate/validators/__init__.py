"""Validation framework for redirect CSVs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


def run_all_validators(
    config: "MigrationConfig",
    dry_run: bool = False,
    verbose: bool = False,
) -> bool:
    """Run all 4 validation layers in sequence. Returns True if all pass."""
    from migrate.validators.csv_format import CSVFormatValidator
    from migrate.validators.loop_detector import LoopDetectorValidator
    from migrate.validators.target_existence import TargetExistenceValidator

    results: list[bool] = []

    console.rule("[bold]Layer 1: Target Existence")
    v1 = TargetExistenceValidator(config)
    results.append(v1.run())

    console.rule("[bold]Layer 2: CSV Format")
    v2 = CSVFormatValidator(config)
    results.append(v2.run())

    console.rule("[bold]Loop Detection (pre-upload)")
    v_loop = LoopDetectorValidator(config)
    results.append(v_loop.run())

    all_passed = all(results)
    if all_passed:
        console.print("\n[green bold]All validation layers passed.[/green bold]")
    else:
        console.print("\n[red bold]Some validation layers failed. Review output above.[/red bold]")

    return all_passed
