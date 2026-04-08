"""Command-line interface for Beacon ICN chain deduplication."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__:
    from .pipeline import run
else:
    # Running as `python beacon/cli.py` — not loaded as a package submodule
    _root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_root))
    from beacon.pipeline import run


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
        nargs="?",
        type=Path,
        default=None,
        help=(
            "path to the Beacon full-load .xlsx file "
            "(default: Beacon_Full_Load.xlsx in the project root)"
        ),
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
    from beacon.paths import PROJECT_ROOT

    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    if args.input is None:
        input_path = (PROJECT_ROOT / "Beacon_Full_Load.xlsx").resolve()
    else:
        input_path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"input file not found: {input_path}")

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
