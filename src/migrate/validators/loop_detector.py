"""Loop Detector — NEW pre-upload graph-based cycle detection.

Analyzes the redirect CSV itself (no HTTP requests needed) to find:
- Direct loops: A -> B -> A
- Chain loops: A -> B -> C -> A
- Long chains: A -> B -> C -> D (exceeding max depth)

This is a new component not present in the original codebase.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from migrate.config import MigrationConfig

console = Console()


class LoopDetectorValidator:
    """Graph-based cycle detection on the redirect CSV before upload."""

    def __init__(self, config: MigrationConfig, csv_path: str | Path | None = None) -> None:
        self.config = config
        self.csv_path = Path(csv_path) if csv_path else self._find_csv()
        self.loops: list[list[str]] = []
        self.long_chains: list[list[str]] = []

    def _find_csv(self) -> Path:
        output_dir = Path(self.config.output.directory) / "06_output"
        for name in ["shopify_redirects_complete.csv", "shopify_redirects_final.csv"]:
            p = output_dir / name
            if p.exists():
                return p
        return output_dir / "shopify_redirects_complete.csv"

    def _load_graph(self) -> dict[str, str]:
        """Load redirect mappings as a directed graph (source -> target)."""
        graph: dict[str, str] = {}
        if not self.csv_path.exists():
            return graph

        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            src_col = tgt_col = None
            for s, t in [("Redirect from", "Redirect to"), ("old_url", "new_url")]:
                if s in fieldnames and t in fieldnames:
                    src_col, tgt_col = s, t
                    break
            if not src_col:
                return graph
            for row in reader:
                source = row.get(src_col, "").strip()
                target = row.get(tgt_col, "").strip()
                if source and target:
                    graph[source] = target

        return graph

    def _find_cycles(self, graph: dict[str, str]) -> None:
        """Walk every redirect chain, detect cycles and long chains."""
        max_depth = self.config.validation.max_chain_depth

        for start in graph:
            visited: list[str] = [start]
            current = graph[start]
            depth = 0

            while current in graph and depth < max_depth + 5:
                if current in visited:
                    # Found a cycle — extract the loop portion
                    loop_start = visited.index(current)
                    self.loops.append(visited[loop_start:] + [current])
                    break
                visited.append(current)
                current = graph[current]
                depth += 1
            else:
                # No cycle but check chain length
                if len(visited) > max_depth:
                    self.long_chains.append(visited)

    def run(self) -> bool:
        """Execute loop detection. Returns True if no loops found."""
        console.rule("[bold]Pre-upload Loop Detection")

        graph = self._load_graph()
        if not graph:
            console.print("[yellow]No redirect data to analyze.[/yellow]")
            return True

        console.print(f"  Analyzing {len(graph)} redirects for loops...")
        self._find_cycles(graph)

        if self.loops:
            console.print(f"  [red]Found {len(self.loops)} redirect loops![/red]")
            for loop in self.loops[:5]:
                console.print(f"    {'  ->  '.join(loop)}")
            if len(self.loops) > 5:
                console.print(f"    ... and {len(self.loops) - 5} more")

        if self.long_chains:
            console.print(
                f"  [yellow]{len(self.long_chains)} chains exceed max depth "
                f"({self.config.validation.max_chain_depth})[/yellow]"
            )

        if not self.loops and not self.long_chains:
            console.print("  [green]No loops or excessive chains detected.[/green]")

        return len(self.loops) == 0
