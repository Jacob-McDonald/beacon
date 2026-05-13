"""Beacon pipeline: orchestrates load, chain reports, MTF enrichment, and output.

Callers build a :class:`PipelineConfig`, hand it to :func:`run`, and
receive a :class:`PipelineResult` describing every artifact that was
produced.  The two-dataclass boundary keeps the pipeline's public
surface explicit: optional inputs are spelled out on the config, and
optional outputs (Verity coverage, Verity_Matches enrichment) are
spelled out on the result.

Progress and diagnostics are emitted through the module's ``logging``
logger (``beacon.pipeline``) — no ``print`` calls — so callers can
silence or redirect output without touching the pipeline itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_ANALYTICS_REPORT_FILE,
    BEACON_COL_RX_NUM,
    BEACON_COL_TXN_DESC,
    DUPLICATE_GROUPS_REPORT_FILE,
    DUPLICATE_PATTERNS_REPORT_FILE,
    FILTERED_EXCEL_OUTPUT_FILE,
    REPORTS_SUBDIR,
    RETAINED_ICNS_REPORT_FILE,
    TRANSACTION_CODE_DESCRIPTIONS,
    VERITY_COVERAGE_REPORT_FILE,
    XREF_CHAIN_REPORT_FILE,
)
from beacon.processing import (
    Chain,
    build_chains,
    build_mtf_lookup,
    enrich_with_mtf,
    enrich_with_transaction_desc,
    get_retained_df,
    load_transactions,
    load_verity_claims_submission,
    write_filtered_excel,
)
from beacon.reports import (
    write_analytics_report,
    write_chain_report,
    write_duplicate_reports,
    write_retained_icns_report,
    write_verity_coverage_report,
)
from beacon.verity_coverage import VerityCoverageStats, verity_coverage_stats
from beacon.verity_matches import (
    VerityMatchesStepResult,
    process_verity_matches,
)

log: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    """Inputs and destination configuration for :func:`run`.

    Attributes:
        input_path: Path to the Beacon full-load ``.xlsx`` file.  Must
                    contain sheet 1 plus the four MTF sheets.
        output_dir: Base directory for output artifacts.  Each run lands
                    in ``<output_dir>/<input-stem>_<YYYY-MM-DD>/``.
                    Defaults to ``<input_parent>/output``.
        verity_path: Optional Verity claims submission rollup used to
                     compute NPI/Rx/Fill overlap.
        verity_matches_path: Optional Verity_Matches ``.xlsx`` (single
                             file) or directory of
                             ``*_Verity_Matches.xlsx`` monthly files.
                             Adds the ``Verity_Matches`` YES/NO column
                             to the exported workbook.
    """

    input_path: Path
    output_dir: Path | None = None
    verity_path: Path | None = None
    verity_matches_path: Path | None = None


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Paths and counters produced by :func:`run`.

    Every report path is a named field instead of a string-keyed dict so
    callers get static-type safety on missing / optional artifacts.
    The three ``*_report`` Path-or-None fields plus ``filtered_verity_matches``
    are only populated when the corresponding input is supplied on the
    :class:`PipelineConfig`.

    Attributes:
        filtered_excel: Path to the primary Beacon_Filtered.xlsx export.
        reports_dir: Directory containing every text report.
        chain_report: Multi-link Xref chain listing.
        retained_icns_report: One-line-per-chain-head ICN listing.
        analytics_report: Aggregate analytics by location / code / chain.
        duplicate_patterns_report: Duplicate ``(Rx, Fill)`` pattern summary.
        duplicate_groups_report: Duplicate ``(Rx, Fill)`` grouped detail.
        verity_coverage_report: Verity claims overlap stats (``-v``).
        verity_matches_report: Verity_Matches diagnostics (``-m``).
        verity_matches_duplicates_report: Per-group
            ``(NPI, Rx, Fill)`` duplicate detail report (``-m``).
        filtered_verity_matches: Pharmacy-filtered combined
                                 Verity_Matches workbook (``-m``).
        total_rows: Total rows read from sheet 1 of the full-load workbook.
        retained_rows: Rows that survived chain filtering (= rows in the
                       exported workbook).
        verity_coverage: Coverage stats when ``-v`` was supplied;
                         ``None`` otherwise.
        verity_matches_yes: YES count from the Verity_Matches column
                            when ``-m`` was supplied; ``None`` otherwise.
        verity_matches_no: NO count from the Verity_Matches column when
                           ``-m`` was supplied; ``None`` otherwise.
    """

    filtered_excel: Path
    reports_dir: Path
    chain_report: Path
    retained_icns_report: Path
    analytics_report: Path
    duplicate_patterns_report: Path
    duplicate_groups_report: Path
    verity_coverage_report: Path | None = None
    verity_matches_report: Path | None = None
    verity_matches_duplicates_report: Path | None = None
    filtered_verity_matches: Path | None = None
    total_rows: int = 0
    retained_rows: int = 0
    verity_coverage: VerityCoverageStats | None = None
    verity_matches_yes: int | None = None
    verity_matches_no: int | None = None


def run(config: PipelineConfig) -> PipelineResult:
    """Execute the full pipeline described by *config*.

    Parameters:
        config: :class:`PipelineConfig` with input path and optional
                supplement / Verity inputs.

    Returns:
        :class:`PipelineResult` describing the artifacts written and
        headline counters (row totals, optional Verity hit/miss stats,
        optional Verity_Matches YES/NO counts).
    """
    # Step 0 — Prepare output directory and paths for generated files.
    # Each run lands in <base>/<input-stem>_<YYYY-MM-DD>/ so artifacts from
    # different inputs (or different days) don't overwrite each other.
    # Re-running on the same input on the same day overwrites the previous
    # run's files.  Text reports live in REPORTS_SUBDIR inside that run
    # folder so the run dir's top level stays focused on the Excel export.
    base_dir: Path = config.output_dir or (config.input_path.parent / "output")
    output_dir: Path = base_dir / f"{config.input_path.stem}_{date.today().isoformat()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    reports_dir: Path = output_dir / REPORTS_SUBDIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    chain_report: Path = reports_dir / XREF_CHAIN_REPORT_FILE
    retained_icns: Path = reports_dir / RETAINED_ICNS_REPORT_FILE
    analytics_path: Path = reports_dir / BEACON_ANALYTICS_REPORT_FILE
    patterns_path: Path = reports_dir / DUPLICATE_PATTERNS_REPORT_FILE
    groups_path: Path = reports_dir / DUPLICATE_GROUPS_REPORT_FILE
    filtered: Path = output_dir / FILTERED_EXCEL_OUTPUT_FILE

    # Step 1 — Load sheet 1 (ICN, Xref, Transaction Code, Pharmacy NPI).
    log.info("Loading %s ...", config.input_path.name)
    df: pd.DataFrame = load_transactions(config.input_path)
    log.info("  %d data rows loaded.", len(df))

    # Step 2 — Build xref→chain graph and list multi-row prescription chains.
    log.info("Building cross-reference chains ...")
    chains: list[Chain] = build_chains(df)
    log.info("  %d chains found.", len(chains))

    # Step 3 — Keep only rows whose ICN is never listed as another row's Xref.
    retained: pd.DataFrame = get_retained_df(df)
    log.info(
        "  %d rows retained, %d discarded.",
        len(retained), len(df) - len(retained),
    )

    # Step 4 — Text report: every chain with row numbers and summary stats.
    log.info("Writing chain report to %s ...", chain_report)
    write_chain_report(chains, len(df), len(retained), chain_report)

    # Step 5 — Text report: one line per chain head (retained ICN only).
    log.info("Writing retained ICNs report to %s ...", retained_icns)
    write_retained_icns_report(chains, retained_icns)

    # Step 6 — Load MTF sheets and join Rx Num / Fill Num onto retained rows.
    log.info("Loading MTF lookup tables ...")
    mtf_lookup: pd.DataFrame = build_mtf_lookup(config.input_path)
    log.info("  %d MTF entries loaded.", len(mtf_lookup))

    log.info("Enriching retained rows with Rx Num / Fill Num ...")
    enriched: pd.DataFrame = enrich_with_mtf(retained, mtf_lookup)
    matched: int = int(enriched[BEACON_COL_RX_NUM].notna().sum())
    log.info("  %d/%d rows matched.", matched, len(enriched))

    # Step 7 — Add human-readable transaction descriptions (static lookup).
    log.info("Adding transaction descriptions ...")
    enriched = enrich_with_transaction_desc(enriched, TRANSACTION_CODE_DESCRIPTIONS)
    desc_matched: int = int(enriched[BEACON_COL_TXN_DESC].notna().sum())
    log.info("  %d/%d codes matched a description.", desc_matched, len(enriched))

    # Step 8 — Text report: analytics by location, codes, chains, Rx/Fill.
    log.info("Writing analytics report to %s ...", analytics_path)
    write_analytics_report(enriched, chains, df, analytics_path)

    # Step 9 — Rx/Fill duplicate reports (pattern summary + grouped detail).
    log.info("Writing duplicate patterns report to %s ...", patterns_path)
    log.info("Writing duplicate groups report to %s ...", groups_path)
    write_duplicate_reports(enriched, chains, df, patterns_path, groups_path)

    # Step 10 — Optional Verity overlap (uses enriched frame in memory).
    coverage: VerityCoverageStats | None = None
    verity_coverage_path: Path | None = None
    if config.verity_path is not None:
        log.info("Verity overlap (%s) ...", config.verity_path.name)
        verity_df: pd.DataFrame = load_verity_claims_submission(config.verity_path)
        coverage = verity_coverage_stats(enriched, verity_df)
        log.info(
            "  Beacon rows: %d; hits: %d; misses: %d; hit rate: %.4f%%",
            coverage.beacon_row_count,
            coverage.hits,
            coverage.misses,
            coverage.hit_rate * 100,
        )
        verity_coverage_path = reports_dir / VERITY_COVERAGE_REPORT_FILE
        log.info("Writing Verity coverage report to %s ...", verity_coverage_path)
        write_verity_coverage_report(enriched, verity_df, verity_coverage_path)

    # Step 11 — Optional Verity_Matches enrichment.  The data work lives
    # in beacon.verity_matches.process_verity_matches; we just log the
    # headline numbers and thread the artifacts into PipelineResult.
    vm_yes: int | None = None
    vm_no: int | None = None
    vm_filtered_path: Path | None = None
    vm_report_path: Path | None = None
    vm_duplicates_report_path: Path | None = None
    if config.verity_matches_path is not None:
        log.info("Loading Verity_Matches from %s ...", config.verity_matches_path)
        vm: VerityMatchesStepResult = process_verity_matches(
            enriched=enriched,
            verity_matches_path=config.verity_matches_path,
            reports_dir=reports_dir,
        )
        combined_rows: int = 0
        for summary in vm.summaries:
            log.info(
                "  %s: %d -> %d rows after NPI filter",
                summary.path.name, summary.rows_before, summary.rows_after,
            )
            combined_rows += summary.rows_after
        log.info("  Combined filtered rows: %d", combined_rows)
        log.info("Wrote filtered Verity_Matches to %s", vm.filtered_path)
        if vm.dupe_report.participant_count > 0:
            log.warning(
                "  %d rows participate in (Rx, Fill) duplicates among Eligible=YES",
                vm.dupe_report.participant_count,
            )
        else:
            log.info("  No (Rx, Fill) duplicates among Eligible=YES rows.")
        if vm.triple_dupe_report.participant_count > 0:
            log.warning(
                "  %d rows participate in (NPI, Rx, Fill) duplicates among Eligible=YES",
                vm.triple_dupe_report.participant_count,
            )
        else:
            log.info("  No (NPI, Rx, Fill) duplicates among Eligible=YES rows.")
        log.info(
            "  Verity_Matches column: %d YES, %d NO",
            vm.yes_count, vm.no_count,
        )
        log.info("Wrote Verity_Matches report to %s", vm.report_path)
        log.info(
            "Wrote Verity_Matches duplicates report to %s",
            vm.duplicates_report_path,
        )

        enriched = vm.enriched
        vm_yes = vm.yes_count
        vm_no = vm.no_count
        vm_filtered_path = vm.filtered_path
        vm_report_path = vm.report_path
        vm_duplicates_report_path = vm.duplicates_report_path

    # Step 12 — Excel export: enriched retained rows.
    log.info("Writing filtered Excel to %s ...", filtered)
    write_filtered_excel(enriched, filtered)

    log.info("Done.")

    return PipelineResult(
        filtered_excel=filtered,
        reports_dir=reports_dir,
        chain_report=chain_report,
        retained_icns_report=retained_icns,
        analytics_report=analytics_path,
        duplicate_patterns_report=patterns_path,
        duplicate_groups_report=groups_path,
        verity_coverage_report=verity_coverage_path,
        verity_matches_report=vm_report_path,
        verity_matches_duplicates_report=vm_duplicates_report_path,
        filtered_verity_matches=vm_filtered_path,
        total_rows=len(df),
        retained_rows=len(retained),
        verity_coverage=coverage,
        verity_matches_yes=vm_yes,
        verity_matches_no=vm_no,
    )
