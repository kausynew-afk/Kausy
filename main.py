"""CLI entry point for the Job Application Agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from agent.config_loader import load_config
from agent.orchestrator import Orchestrator


def setup_logging(level: str = "INFO") -> None:
    console = logging.StreamHandler(sys.stdout)
    console.setStream(open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            console,
            logging.FileHandler("data/logs/agent.log", encoding="utf-8"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Job Application Agent — finds jobs, tailors resumes, emails you",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python main.py                           # Run with default config.yaml
  python main.py --config my_config.yaml   # Use a custom config
  python main.py --dry-run                 # Scrape and analyse only, no emails sent
  python main.py --verbose                 # Enable debug-level logging
        """,
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to YAML config file (default: config.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape and score only — no emails sent",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()

    Path("data/logs").mkdir(parents=True, exist_ok=True)
    setup_logging("DEBUG" if args.verbose else "INFO")

    logger = logging.getLogger("main")
    logger.info("Loading config from: %s", args.config)

    config = load_config(args.config)

    if args.dry_run:
        config.setdefault("safety", {})["max_applications_per_run"] = 0
        logger.info("DRY RUN mode — no jobs will be processed")

    orchestrator = Orchestrator(config)
    run_result = asyncio.run(orchestrator.run())

    try:
        orchestrator.emailer.send_summary_report(
            records=run_result["records"],
            run_id=run_result["run_id"],
            stats=run_result,
        )
    except Exception as e:
        logger.warning("Summary email failed (non-fatal): %s", e)


if __name__ == "__main__":
    main()
