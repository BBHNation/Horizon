"""Command-line entry point for the comprehensive news digest."""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv
from rich.console import Console

from ..storage.manager import ConfigError, StorageManager
from .orchestrator import NewsDigestOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a multi-source comprehensive news report")
    parser.add_argument("--hours", type=int, help="Fetch material from the last N hours")
    args = parser.parse_args()
    load_dotenv()
    console = Console()
    storage = StorageManager(data_dir="data")
    try:
        config = storage.load_config()
        asyncio.run(NewsDigestOrchestrator(config, storage, console=console).run(force_hours=args.hours))
    except (ConfigError, ValueError, RuntimeError) as exc:
        console.print(f"[bold red]❌ News Digest failed: {exc}[/bold red]")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
