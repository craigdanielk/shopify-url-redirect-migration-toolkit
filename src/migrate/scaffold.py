"""Project scaffolding for new migration projects."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console

console = Console()

TEMPLATE_DIRS = [
    "00_source_data/source",
    "00_source_data/target",
    "01_normalized_data",
    "03_mapping_rules",
    "04_redirect_mapping",
    "06_output",
    "tests/pre-launch/validation_reports",
]


def scaffold_project(name: str, output_dir: str = ".") -> Path:
    """Create a new migration project directory with standard structure."""
    root = Path(output_dir) / name
    if root.exists():
        console.print(f"[yellow]Directory already exists: {root}[/yellow]")
        return root

    root.mkdir(parents=True)

    for d in TEMPLATE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)

    # Copy config template
    template = Path(__file__).parent.parent.parent / "config.example.yaml"
    dest_config = root / "config.yaml"
    if template.exists():
        shutil.copy2(template, dest_config)
    else:
        # Inline minimal config
        config_text = (
            f"project:\n  name: {name}\n  description: ''\n\n"
            f"source:\n  platform: csv\n\n"
            f"target:\n  platform: shopify\n"
        )
        dest_config.write_text(config_text, encoding="utf-8")

    # .env placeholder
    env_file = root / ".env"
    env_file.write_text(
        "# Credentials — see .env.example in the toolkit root for reference\n",
        encoding="utf-8",
    )

    console.print(f"[green]Created migration project:[/green] {root}")
    console.print("  Edit config.yaml with your source/target details.")
    console.print("  Then run: migrate fetch --config config.yaml")
    return root
