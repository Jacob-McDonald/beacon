"""Command-line interface for Beacon ICN chain deduplication."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from beacon.constants import DEFAULT_INPUT_FILENAME
from beacon.paths import PROJECT_ROOT
from beacon.pipeline import PipelineConfig, run


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
            f"path to the Beacon full-load .xlsx file "
            f"(default: {DEFAULT_INPUT_FILENAME} in the project root)"
        ),
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "base directory for output. A subfolder named "
            "<input-stem>_<YYYY-MM-DD> is created inside it. "
            "(default: an `output/` folder next to the input file)"
        ),
    )
    parser.add_argument(
        "-v",
        "--verity",
        type=Path,
        default=None,
        help=(
            "path to Verity_Claims_Submission rollup for in-memory overlap stats "
            "(NPI / Rx / Fill vs export)"
        ),
    )
    parser.add_argument(
        "-m",
        "--verity-matches",
        type=Path,
        default=None,
        help=(
            "path to a Verity_Matches .xlsx OR a folder of monthly "
            "*_Verity_Matches.xlsx files; adds a Verity_Matches YES/NO column "
            "to the enriched Beacon frame"
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress progress output; only errors are printed to stderr",
    )
    return parser


def _configure_logging(*, quiet: bool) -> None:
    """Install a minimal stdout handler on ``beacon``'s logger tree.

    The pipeline logs progress at INFO and warnings (duplicate audits,
    etc.) at WARNING.  The format is intentionally plain — just the
    message — so the on-screen output matches the previous ``print``
    style callers are used to.
    """
    level: int = logging.WARNING if quiet else logging.INFO
    handler: logging.Handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root: logging.Logger = logging.getLogger("beacon")
    root.setLevel(level)
    # Replace existing handlers so repeated calls (e.g. test harness)
    # don't accumulate duplicate output.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.propagate = False


def main() -> None:
    """Parse arguments and run the deduplication pipeline."""
    parser: argparse.ArgumentParser = build_parser()
    args: argparse.Namespace = parser.parse_args()

    _configure_logging(quiet=args.quiet)

    if args.input is None:
        input_path = (PROJECT_ROOT / DEFAULT_INPUT_FILENAME).resolve()
    else:
        input_path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"input file not found: {input_path}")

    output_dir: Path | None = None
    if args.output_dir is not None:
        output_dir = args.output_dir.resolve()

    verity_path: Path | None = None
    if args.verity is not None:
        resolved_verity: Path = args.verity.resolve()
        if not resolved_verity.is_file():
            parser.error(f"verity file not found: {resolved_verity}")
        verity_path = resolved_verity

    verity_matches_path: Path | None = None
    if args.verity_matches is not None:
        resolved: Path = args.verity_matches.resolve()
        if not resolved.exists():
            parser.error(f"verity-matches path not found: {resolved}")
        verity_matches_path = resolved

    config: PipelineConfig = PipelineConfig(
        input_path=input_path,
        output_dir=output_dir,
        verity_path=verity_path,
        verity_matches_path=verity_matches_path,
    )
    try:
        run(config)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
