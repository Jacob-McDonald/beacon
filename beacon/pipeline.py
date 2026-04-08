"""Beacon pipeline: orchestrates load, chain reports, MTF enrichment, and output."""

from __future__ import annotations

from pathlib import Path

from beacon.constants import (
    BEACON_ANALYTICS_REPORT_FILE,
    FILTERED_EXCEL_OUTPUT_FILE,
    RETAINED_ICNS_REPORT_FILE,
    TRANSACTION_CODE_DESCRIPTIONS,
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
    write_filtered_excel,
)
from beacon.reports import (
    write_analytics_report,
    write_chain_report,
    write_retained_icns_report,
)


def run(input_path: Path, output_dir: Path | None = None) -> None:
    """Full pipeline: load, chain-build, report, and filter.

    Parameters:
        input_path: Path to the Beacon full-load .xlsx file.
        output_dir: Directory for output files.  Defaults to the input
                    file's parent directory.
    """
    # Step 0 — Prepare output directory and paths for generated files.
    if output_dir is None:
        output_dir = input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    chain_report: Path = output_dir / XREF_CHAIN_REPORT_FILE
    retained_icns: Path = output_dir / RETAINED_ICNS_REPORT_FILE
    filtered: Path = output_dir / FILTERED_EXCEL_OUTPUT_FILE

    # Step 1 — Load sheet 1 (ICN, Xref, Transaction Code, Pharmacy NPI).
    print(f"Loading {input_path.name} ...")
    df = load_transactions(input_path)
    print(f"  {len(df)} data rows loaded.")

    all_xrefs: set[str] = set(df["Xref"].dropna())

    # Step 2 — Build xref→chain graph and list multi-row prescription chains.
    print("Building cross-reference chains ...")
    chains: list[Chain] = build_chains(df, all_xrefs)
    print(f"  {len(chains)} chains found.")

    # Step 3 — Keep only rows whose ICN is never listed as another row's Xref.
    retained = get_retained_df(df, all_xrefs)
    print(f"  {len(retained)} rows retained, {len(df) - len(retained)} discarded.")

    # Step 4 — Text report: every chain with row numbers and summary stats.
    print(f"Writing chain report to {chain_report} ...")
    write_chain_report(chains, len(df), len(retained), chain_report)

    # Step 5 — Text report: one line per chain head (retained ICN only).
    print(f"Writing retained ICNs report to {retained_icns} ...")
    write_retained_icns_report(chains, retained_icns)

    # Step 6 — Load MTF sheets and join Rx Num / Fill Num onto retained rows.
    print("Loading MTF lookup tables ...")
    mtf_lookup = build_mtf_lookup(input_path)
    print(f"  {len(mtf_lookup)} MTF entries loaded.")

    print("Enriching retained rows with Rx Num / Fill Num ...")
    enriched = enrich_with_mtf(retained, mtf_lookup)
    matched: int = int(enriched["Rx Num"].notna().sum())
    print(f"  {matched}/{len(enriched)} rows matched.")

    # Step 7 — Add human-readable transaction descriptions (static lookup in constants).
    print("Adding transaction descriptions ...")
    enriched = enrich_with_transaction_desc(enriched, TRANSACTION_CODE_DESCRIPTIONS)
    desc_matched: int = int(enriched["Transaction Description"].notna().sum())
    print(f"  {desc_matched}/{len(enriched)} codes matched a description.")

    # Step 8 — Text report: analytics by location, codes, chains, Rx/Fill.
    analytics: Path = output_dir / BEACON_ANALYTICS_REPORT_FILE
    print(f"Writing analytics report to {analytics.name} ...")
    write_analytics_report(enriched, chains, df, analytics)

    # Step 9 — Excel export: enriched retained rows (BeaconT2.xlsx).
    print(f"Writing filtered Excel to {filtered} ...")
    write_filtered_excel(enriched, filtered)

    print("Done.")
