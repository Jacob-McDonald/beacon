"""Text report writers for chain listings and analytics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon.constants import NPI_TO_SHEET
from beacon.processing import Chain, ChainLink


def write_chain_report(
    chains: list[Chain],
    total_rows: int,
    retained_count: int,
    path: Path,
) -> None:
    """Write a human-readable chain report to a text file.

    Parameters:
        chains: List of chains from build_chains().
        total_rows: Total data rows in the original spreadsheet.
        retained_count: Number of rows kept after deduplication.
        path: Output file path.
    """
    lines: list[str] = []
    # Header block matching the fixed-width column layout
    lines.append("")
    lines.append("")
    lines.append("           ICN              ICN Xref")
    lines.append("")

    # Each chain is printed as a group separated by blank lines.
    # Row numbers are 1-based to match spreadsheet rows.
    for chain in chains:
        lines.append("")
        for link in chain:
            row_display: int = link.index + 1
            xref_str: str = f"  {link.xref}" if link.xref is not None else ""
            lines.append(f"      {row_display:>4} {link.icn}{xref_str} ")
        lines.append("")

    # Tally chains by depth for the summary (e.g. "2-link chains: 310")
    length_counts: dict[int, int] = {}
    for chain in chains:
        length: int = len(chain)
        length_counts[length] = length_counts.get(length, 0) + 1

    discarded: int = total_rows - retained_count
    lines.append("")
    lines.append("=" * 60)
    lines.append("  Summary")
    lines.append("=" * 60)
    lines.append(f"  Total rows in spreadsheet:  {total_rows}")
    lines.append(f"  Rows retained (kept):       {retained_count}")
    lines.append(f"  Rows discarded (superseded): {discarded}")
    lines.append(f"  Number of chains:           {len(chains)}")
    lines.append("  Chain length distribution:")
    for length in sorted(length_counts):
        lines.append(f"    {length}-link chains: {length_counts[length]}")
    lines.append("=" * 60)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_retained_icns_report(chains: list[Chain], path: Path) -> None:
    """Write a report listing only the retained ICN from each chain.

    The retained ICN is the final link in each chain — the one whose
    ICN does not appear in any other row's Xref column. Sorted by
    chain length descending so the most complex duplicates are at the top.

    Parameters:
        chains: List of chains from build_chains().
        path: Output file path.
    """
    sorted_chains: list[Chain] = sorted(
        chains, key=lambda c: len(c), reverse=True,
    )

    lines: list[str] = ["", "", ""]

    for chain in sorted_chains:
        # The last link is the head of the chain — the one to retain
        head: ChainLink = chain[-1]
        row_display: int = head.index + 1

        if head.xref is not None:
            mid: str = f"  {head.xref}{row_display:>12}"
        else:
            mid = f"{row_display:>29}"

        lines.append(f"         {head.icn}{mid}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _location_name(npi: str) -> str:
    """Short location label for display, falling back to raw NPI."""
    return NPI_TO_SHEET.get(npi, npi).removeprefix("MTF - ")


def write_analytics_report(
    enriched: pd.DataFrame,
    chains: list[Chain],
    full_df: pd.DataFrame,
    path: Path,
) -> None:
    """Write a comprehensive analytics text report.

    Sections: overall summary, transaction code distribution by location,
    chain statistics by location, and Rx/Fill analysis.

    Parameters:
        enriched: Retained rows after MTF enrichment (with Rx Num, Fill Num,
                  and optionally Transaction Description).
        chains: Chain list from build_chains().
        full_df: The unfiltered DataFrame (for total row count and NPI
                 lookups on chain origins).
        path: Output file path.
    """
    locations: list[str] = list(NPI_TO_SHEET.keys())
    loc_names: list[str] = [_location_name(n) for n in locations]
    total_rows: int = len(full_df)
    retained_count: int = len(enriched)
    discarded: int = total_rows - retained_count

    lines: list[str] = []

    # ── Section 1: Overall Summary ──────────────────────────────────────

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

    length_counts: dict[int, int] = {}
    for chain in chains:
        length_counts[len(chain)] = length_counts.get(len(chain), 0) + 1
    lines.append("  Chain length distribution:")
    for depth in sorted(length_counts):
        lines.append(f"    {depth}-link chains: {length_counts[depth]}")
    lines.append("")

    lines.append("  Rows by location:")
    for npi, name in zip(locations, loc_names):
        count: int = int((enriched["Pharmacy NPI"] == npi).sum())
        lines.append(f"    {name:<14s}  {count:>5}")
    lines.append("")
    lines.append("")

    # ── Section 2: Transaction Code Distribution by Location ────────────

    lines.append("  TRANSACTION CODE DISTRIBUTION BY LOCATION")
    lines.append("  " + "-" * 40)
    lines.append("")

    has_desc: bool = "Transaction Description" in enriched.columns
    codes: list[str] = sorted(enriched["Transaction Code"].dropna().unique())

    # Build description lookup from the enriched data itself
    desc_map: dict[str, str] = {}
    if has_desc:
        for code in codes:
            first: pd.Series = enriched.loc[
                enriched["Transaction Code"] == code, "Transaction Description"
            ].dropna()
            if len(first) > 0:
                desc_map[code] = str(first.iloc[0])

    # Determine column widths
    desc_width: int = max(
        (len(desc_map.get(c, "")) for c in codes), default=0,
    )
    desc_width = max(desc_width, 11)  # "Description" header
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
                ((enriched["Transaction Code"] == code)
                 & (enriched["Pharmacy NPI"] == npi)).sum()
            )
            row_total += n
            row_parts.append(f"  {n:>{col_w}d}")
        row_parts.append(f"  {row_total:>{col_w}d}")
        lines.append("".join(row_parts))

    # Totals row
    total_parts: list[str] = [
        f"  {'':5s}  {'Total':<{desc_width}s}",
    ]
    grand: int = 0
    for npi in locations:
        loc_total: int = int((enriched["Pharmacy NPI"] == npi).sum())
        grand += loc_total
        total_parts.append(f"  {loc_total:>{col_w}d}")
    total_parts.append(f"  {grand:>{col_w}d}")
    lines.append("  " + "-" * (len(header) - 2))
    lines.append("".join(total_parts))
    lines.append("")
    lines.append("")

    # ── Section 3: Chain Statistics by Location ─────────────────────────

    lines.append("  CHAIN STATISTICS BY LOCATION")
    lines.append("  " + "-" * 40)
    lines.append("")

    # Tag each chain's origin by looking up its first link's NPI
    icn_to_npi: dict[str, str] = dict(
        zip(full_df["ICN"], full_df["Pharmacy NPI"]),
    )

    chains_by_loc: dict[str, list[Chain]] = {npi: [] for npi in locations}
    for chain in chains:
        origin_npi: str | None = icn_to_npi.get(chain[0].icn)
        if origin_npi in chains_by_loc:
            chains_by_loc[origin_npi].append(chain)

    for npi, name in zip(locations, loc_names):
        loc_chains: list[Chain] = chains_by_loc[npi]
        lines.append(f"  {name}")
        lines.append(f"    Chains: {len(loc_chains)}")
        if loc_chains:
            loc_depth: dict[int, int] = {}
            for chain in loc_chains:
                loc_depth[len(chain)] = loc_depth.get(len(chain), 0) + 1
            for depth in sorted(loc_depth):
                lines.append(
                    f"      {depth}-link: {loc_depth[depth]}"
                )
        lines.append("")
    lines.append("")

    # ── Section 4: Rx Num / Fill Num Analysis ───────────────────────────

    lines.append("  RX NUM / FILL NUM ANALYSIS")
    lines.append("  " + "-" * 40)
    lines.append("")

    for npi, name in zip(locations, loc_names):
        subset: pd.DataFrame = enriched[enriched["Pharmacy NPI"] == npi]
        rx_valid: pd.Series = subset["Rx Num"].dropna()
        fill_valid: pd.Series = subset["Fill Num"].dropna()
        unique_rx: int = rx_valid.nunique()

        lines.append(f"  {name}")
        lines.append(f"    Retained rows:  {len(subset)}")
        lines.append(f"    Unique Rx Nums: {unique_rx}")

        # Fill distribution
        if len(fill_valid) > 0:
            fill_counts: pd.Series = fill_valid.value_counts().sort_index()
            lines.append("    Fill Num distribution:")
            for fill_val, cnt in fill_counts.items():
                label: str = "new" if str(fill_val) == "0" else "refill"
                lines.append(f"      Fill {fill_val:>3s}: {cnt:>5d}  ({label})")

        # Rx numbers appearing more than once (multiple fills)
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

    path.write_text("\n".join(lines), encoding="utf-8")
