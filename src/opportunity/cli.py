"""Command-line entry point for Startup Radar."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from ..storage.manager import ConfigError, StorageManager
from .orchestrator import StartupRadarOrchestrator


console = Console()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Startup Radar - discover indie-developer startup opportunities"
    )
    parser.add_argument("--hours", type=int, help="Fetch material from the last N hours")
    parser.add_argument("--profile", type=Path, help="Override the profile.yml path")
    parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="Analyze articles again even if they already exist in SQLite",
    )
    args = parser.parse_args()
    load_dotenv()

    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
        orchestrator = StartupRadarOrchestrator(
            config,
            storage,
            profile_path=args.profile,
            console=console,
        )
        asyncio.run(orchestrator.run(force_hours=args.hours, reanalyze=args.reanalyze))
    except (FileNotFoundError, ConfigError, ValueError, RuntimeError) as exc:
        console.print(f"[bold red]❌ Startup Radar failed: {exc}[/bold red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
