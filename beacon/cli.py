"""Command-line interface for Beacon ICN chain deduplication."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="beacon",
        description=(
            "Analyse cross-reference chains in a Beacon full-load spreadsheet, "
            "produce chain reports, and write a filtered Excel file retaining "
            "only the head-of-chain records."
        ),
    )
    parser.add_argument(
        "input",
        type=Path,
        help="path to the Beacon full-load .xlsx file",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="directory for output files (default: same as input file)",
    )
    return parser


def main() -> None:
    """Parse arguments and run the deduplication pipeline."""
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    input_path: Path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"input file not found: {args.input}")

    output_dir: Path | None = None
    if args.output_dir is not None:
        output_dir = args.output_dir.resolve()

    try:
        run(input_path, output_dir)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
