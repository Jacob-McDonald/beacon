"""Beacon pipeline: orchestrates load, chain reports, MTF enrichment, and output."""

from __future__ import annotations

from pathlib import Path

from beacon.constants import (
    ANALYTICS_NAME,
    CHAIN_REPORT_NAME,
    FILTERED_NAME,
    RETAINED_ICNS_NAME,
    TRANSACTION_CODES_NAME,
)
from beacon.processing import (
    Chain,
    build_chains,
    build_mtf_lookup,
    enrich_with_mtf,
    enrich_with_transaction_desc,
    get_retained_df,
    load_transaction_descriptions,
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
    if output_dir is None:
        output_dir = input_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    chain_report: Path = output_dir / CHAIN_REPORT_NAME
    retained_icns: Path = output_dir / RETAINED_ICNS_NAME
    filtered: Path = output_dir / FILTERED_NAME

    print(f"Loading {input_path.name} ...")
    df = load_transactions(input_path)
    print(f"  {len(df)} data rows loaded.")

    all_xrefs: set[str] = set(df["Xref"].dropna())

    print("Building cross-reference chains ...")
    chains: list[Chain] = build_chains(df, all_xrefs)
    print(f"  {len(chains)} chains found.")

    retained = get_retained_df(df, all_xrefs)
    print(f"  {len(retained)} rows retained, {len(df) - len(retained)} discarded.")

    print(f"Writing chain report to {chain_report} ...")
    write_chain_report(chains, len(df), len(retained), chain_report)

    print(f"Writing retained ICNs report to {retained_icns} ...")
    write_retained_icns_report(chains, retained_icns)

    print("Loading MTF lookup tables ...")
    mtf_lookup = build_mtf_lookup(input_path)
    print(f"  {len(mtf_lookup)} MTF entries loaded.")

    print("Enriching retained rows with Rx Num / Fill Num ...")
    enriched = enrich_with_mtf(retained, mtf_lookup)
    matched: int = int(enriched["Rx Num"].notna().sum())
    print(f"  {matched}/{len(enriched)} rows matched.")

    tx_codes_path: Path = input_path.parent / TRANSACTION_CODES_NAME
    if tx_codes_path.is_file():
        print(f"Loading transaction descriptions from {tx_codes_path.name} ...")
        descriptions = load_transaction_descriptions(tx_codes_path)
        enriched = enrich_with_transaction_desc(enriched, descriptions)
        desc_matched: int = int(enriched["Transaction Description"].notna().sum())
        print(f"  {desc_matched}/{len(enriched)} codes matched a description.")
    else:
        print(f"  {tx_codes_path.name} not found — skipping transaction descriptions.")

    analytics: Path = output_dir / ANALYTICS_NAME
    print(f"Writing analytics report to {analytics.name} ...")
    write_analytics_report(enriched, chains, df, analytics)

    print(f"Writing filtered Excel to {filtered} ...")
    write_filtered_excel(enriched, filtered)

    print("Done.")
