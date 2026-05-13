"""Top-line analytics report writer.

The report is composed of four sections — overall summary, transaction
code distribution, chain statistics, Rx/Fill analysis — each produced
by a small helper so they can evolve independently.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_COL_FILL_NUM,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_RX_NUM,
    BEACON_COL_TXN_CODE,
    BEACON_COL_TXN_DESC,
    NPI_TO_SHEET,
)
from beacon.processing import Chain
from beacon.reports._common import location_name
from beacon.reports.chains import tally_chain_lengths


def _overall_summary_section(
    enriched: pd.DataFrame,
    chains: list[Chain],
    total_rows: int,
    locations: list[str],
    loc_names: list[str],
) -> list[str]:
    """Report header and high-level counts."""
    retained_count: int = len(enriched)
    discarded: int = total_rows - retained_count

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  BEACON ANALYTICS REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append("  OVERALL SUMMARY")
    lines.append("  " + "-" * 40)
    lines.append(f"  Total rows in spreadsheet:   {total_rows}")
    lines.append(f"  Rows retained (kept):        {retained_count}")
    lines.append(f"  Rows discarded (superseded): {discarded}")
    lines.append(f"  Number of chains:            {len(chains)}")
    lines.append("")

    length_counts: dict[int, int] = tally_chain_lengths(chains)
    lines.append("  Chain length distribution:")
    for depth in sorted(length_counts):
        lines.append(f"    {depth}-link chains: {length_counts[depth]}")
    lines.append("")

    lines.append("  Rows by location:")
    for npi, name in zip(locations, loc_names):
        count: int = int((enriched[BEACON_COL_PHARMACY_NPI] == npi).sum())
        lines.append(f"    {name:<14s}  {count:>5}")
    lines.append("")
    lines.append("")
    return lines


def _transaction_code_section(
    enriched: pd.DataFrame,
    locations: list[str],
    loc_names: list[str],
) -> list[str]:
    """Transaction code distribution cross-tabulated by location."""
    lines: list[str] = []
    lines.append("  TRANSACTION CODE DISTRIBUTION BY LOCATION")
    lines.append("  " + "-" * 40)
    lines.append("")

    has_desc: bool = BEACON_COL_TXN_DESC in enriched.columns
    codes: list[str] = sorted(enriched[BEACON_COL_TXN_CODE].dropna().unique())

    desc_map: dict[str, str] = {}
    if has_desc:
        for code in codes:
            first: pd.Series = enriched.loc[
                enriched[BEACON_COL_TXN_CODE] == code, BEACON_COL_TXN_DESC
            ].dropna()
            if len(first) > 0:
                desc_map[code] = str(first.iloc[0])

    desc_width: int = max(
        (len(desc_map.get(c, "")) for c in codes), default=0,
    )
    desc_width = max(desc_width, 11)
    col_w: int = max(max((len(n) for n in loc_names), default=10), 5) + 2

    header: str = (
        f"  {'Code':<5s}  {'Description':<{desc_width}s}"
        + "".join(f"  {n:>{col_w}s}" for n in loc_names)
        + f"  {'Total':>{col_w}s}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for code in codes:
        desc: str = desc_map.get(code, "")
        row_parts: list[str] = [f"  {code:<5s}  {desc:<{desc_width}s}"]
        row_total: int = 0
        for npi in locations:
            n: int = int(
                ((enriched[BEACON_COL_TXN_CODE] == code)
                 & (enriched[BEACON_COL_PHARMACY_NPI] == npi)).sum()
            )
            row_total += n
            row_parts.append(f"  {n:>{col_w}d}")
        row_parts.append(f"  {row_total:>{col_w}d}")
        lines.append("".join(row_parts))

    total_parts: list[str] = [
        f"  {'':5s}  {'Total':<{desc_width}s}",
    ]
    grand: int = 0
    for npi in locations:
        loc_total: int = int((enriched[BEACON_COL_PHARMACY_NPI] == npi).sum())
        grand += loc_total
        total_parts.append(f"  {loc_total:>{col_w}d}")
    total_parts.append(f"  {grand:>{col_w}d}")
    lines.append("  " + "-" * (len(header) - 2))
    lines.append("".join(total_parts))
    lines.append("")
    lines.append("")
    return lines


def _chain_stats_section(
    chains: list[Chain],
    locations: list[str],
    loc_names: list[str],
) -> list[str]:
    """Chain counts and depth distribution broken out by pharmacy location."""
    lines: list[str] = []
    lines.append("  CHAIN STATISTICS BY LOCATION")
    lines.append("  " + "-" * 40)
    lines.append("")

    # Each Chain already carries its origin NPI (precomputed in
    # ``build_chains``), so grouping is a direct attribute read.
    chains_by_loc: dict[str, list[Chain]] = {npi: [] for npi in locations}
    for chain in chains:
        if chain.origin_npi in chains_by_loc:
            chains_by_loc[chain.origin_npi].append(chain)

    for npi, name in zip(locations, loc_names):
        loc_chains: list[Chain] = chains_by_loc[npi]
        lines.append(f"  {name}")
        lines.append(f"    Chains: {len(loc_chains)}")
        if loc_chains:
            loc_depth: dict[int, int] = tally_chain_lengths(loc_chains)
            for depth in sorted(loc_depth):
                lines.append(f"      {depth}-link: {loc_depth[depth]}")
        lines.append("")
    lines.append("")
    return lines


def _rx_fill_section(
    enriched: pd.DataFrame,
    locations: list[str],
    loc_names: list[str],
) -> list[str]:
    """Rx Num / Fill Num breakdown per location."""
    lines: list[str] = []
    lines.append("  RX NUM / FILL NUM ANALYSIS")
    lines.append("  " + "-" * 40)
    lines.append("")

    for npi, name in zip(locations, loc_names):
        subset: pd.DataFrame = enriched[enriched[BEACON_COL_PHARMACY_NPI] == npi]
        rx_valid: pd.Series = subset[BEACON_COL_RX_NUM].dropna()
        fill_valid: pd.Series = subset[BEACON_COL_FILL_NUM].dropna()
        unique_rx: int = rx_valid.nunique()

        lines.append(f"  {name}")
        lines.append(f"    Retained rows:  {len(subset)}")
        lines.append(f"    Unique Rx Nums: {unique_rx}")

        if len(fill_valid) > 0:
            fill_counts: pd.Series = fill_valid.value_counts().sort_index()
            lines.append("    Fill Num distribution:")
            for fill_val, cnt in fill_counts.items():
                label: str = "new" if str(fill_val) == "0" else "refill"
                lines.append(f"      Fill {fill_val:>3s}: {cnt:>5d}  ({label})")

        rx_dupes: pd.Series = rx_valid.value_counts()
        multi_fill_rx: pd.Series = rx_dupes[rx_dupes > 1]
        if len(multi_fill_rx) > 0:
            lines.append(
                f"    Rx Nums with multiple retained rows: {len(multi_fill_rx)}"
            )
            for rx, cnt in multi_fill_rx.head(5).items():
                lines.append(f"      {rx}: {cnt} rows")
            if len(multi_fill_rx) > 5:
                lines.append(f"      ... and {len(multi_fill_rx) - 5} more")
        else:
            lines.append("    No Rx Nums with multiple retained rows.")

        lines.append("")

    lines.append("=" * 80)
    lines.append("")
    return lines


def write_analytics_report(
    enriched: pd.DataFrame,
    chains: list[Chain],
    full_df: pd.DataFrame,
    path: Path,
) -> None:
    """Write a comprehensive analytics text report.

    Composes four sections: overall summary, transaction code distribution
    by location, chain statistics by location, and Rx/Fill analysis.

    Parameters:
        enriched: Retained rows after MTF enrichment (with Rx Num,
                  Fill Num, and optionally Transaction Description).
        chains: Chain list from ``build_chains``.
        full_df: The unfiltered DataFrame (used only for the total row
                 count in the overall summary section).
        path: Output file path.
    """
    locations: list[str] = list(NPI_TO_SHEET.keys())
    loc_names: list[str] = [location_name(n) for n in locations]
    total_rows: int = len(full_df)

    lines: list[str] = []
    lines += _overall_summary_section(enriched, chains, total_rows, locations, loc_names)
    lines += _transaction_code_section(enriched, locations, loc_names)
    lines += _chain_stats_section(chains, locations, loc_names)
    lines += _rx_fill_section(enriched, locations, loc_names)

    path.write_text("\n".join(lines), encoding="utf-8")
