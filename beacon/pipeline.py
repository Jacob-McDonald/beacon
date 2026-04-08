"""Beacon ICN Chain Deduplication.

Reads the first sheet of a Beacon full-load .xlsx, discovers cross-reference
chains between prescription transactions, produces chain reports, and writes
a filtered Excel file containing only the retained (head-of-chain) records.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pandas as pd

REQUIRED_COLUMNS: list[str] = ["ICN", "Xref", "Transaction Code", "Pharmacy NPI"]
CHAIN_REPORT_NAME: str = "Xref_Chain_Report.txt"
RETAINED_ICNS_NAME: str = "ICN_Retained.txt"
FILTERED_NAME: str = "BeaconT2.xlsx"
TRANSACTION_CODES_NAME: str = "BeaconMFPTransactionCodes.xlsx"
ANALYTICS_NAME: str = "Beacon_Analytics.txt"

NPI_TO_SHEET: dict[str, str] = {
    "1073835591": "MTF - Specialty",
    "1194345199": "MTF - CDA",
    "1235986290": "MTF - Hayden",
    "1487401451": "MTF - Post Falls",
}


class ChainLink(NamedTuple):
    """A single row in a cross-reference chain."""

    index: int
    icn: str
    xref: str | None


# Ordered list of links from oldest (original) to newest (head)
Chain = list[ChainLink]


def load_transactions(path: Path) -> pd.DataFrame:
    """Load required columns from the first sheet of the spreadsheet.

    Parameters:
        path: Path to the .xlsx file whose first sheet contains columns
              ICN, Xref, and Transaction Code.

    Returns:
        DataFrame with only the required columns, nullable StringDtype,
        and a 0-based pandas index.

    Raises:
        FileNotFoundError: If the path does not exist or is not a file.
        RuntimeError: If the Excel file cannot be read.
    """
    # Fail fast with a clear message rather than a cryptic openpyxl error
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Path is not a file: {path}")

    try:
        # dtype="string" keeps ICNs as text so leading zeros are preserved
        df: pd.DataFrame = pd.read_excel(
            path,
            sheet_name=0,
            usecols=REQUIRED_COLUMNS,
            engine="openpyxl",
            dtype="string",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to read Excel file: {path}") from exc

    # Excel column headers sometimes carry trailing whitespace
    df.columns = df.columns.str.strip()
    return df


def build_chains(df: pd.DataFrame, all_xrefs: set[str]) -> list[Chain]:
    """Build cross-reference chains from the transaction data.

    A chain starts at an original row (Xref is null) whose ICN was later
    superseded (appears as someone else's Xref). Each successive link is
    the row whose Xref equals the previous link's ICN.

    Parameters:
        df: Transaction DataFrame with ICN, Xref columns.
        all_xrefs: Set of all non-null Xref values (superseded ICNs).

    Returns:
        List of chains. Each chain is a list of (index, icn, xref) tuples
        ordered from oldest to newest. Only multi-link chains are included.
    """
    # Chain Links: maps a superseded ICN to the row that replaced it.
    # Only rows WITH an Xref value participate here. A row has an Xref
    # when the prescription was resubmitted through the switch — the Xref
    # column records the ICN of the previous submission it replaced.
    # Rows WITHOUT an Xref were never a replacement for anything; they are
    # either standalone prescriptions or the first submission in a chain.
    # Key = the superseded ICN (found in the replacing row's Xref column).
    # Value = ChainLink of the replacing row.
    has_xref: pd.DataFrame = df.dropna(subset=["Xref"])
    xref_rows: dict[str, ChainLink] = {
        row.Xref: ChainLink(row.Index, row.ICN, row.Xref)
        for row in has_xref.itertuples()
    }

    # Chain origins: the first submission of a prescription that was
    # subsequently resubmitted. These rows have no Xref (nothing before
    # them), but their ICN appears in another row's Xref (something
    # replaced them). Each origin is the starting point of a chain.
    is_original: pd.Series = df["Xref"].isna()
    was_superseded: pd.Series = df["ICN"].isin(all_xrefs)
    origins: pd.DataFrame = df[is_original & was_superseded]

    # Walk each chain forward from origin to head
    chains: list[Chain] = []
    for row in origins.itertuples():
        chain: Chain = [ChainLink(row.Index, row.ICN, None)]
        current_icn: str = row.ICN

        # Follow the forward lookup until no row references current_icn
        while current_icn in xref_rows:
            link: ChainLink = xref_rows[current_icn]
            chain.append(link)
            current_icn = link.icn

        if len(chain) > 1:
            chains.append(chain)

    return chains


def get_retained_df(df: pd.DataFrame, all_xrefs: set[str]) -> pd.DataFrame:
    """Return the subset of rows to keep after deduplication.

    A row is retained if its ICN never appears as any other row's Xref,
    meaning it was never superseded by a later transaction.

    Parameters:
        df: Transaction DataFrame with ICN and Xref columns.
        all_xrefs: Set of all non-null Xref values (superseded ICNs).

    Returns:
        Filtered DataFrame containing only the retained rows.
    """
    # Keep rows whose ICN was never superseded
    mask: pd.Series = ~df["ICN"].isin(all_xrefs)  # type: ignore[assignment]
    return df[mask].copy()


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


def build_mtf_lookup(
    source: Path,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load all MTF sheets and return a unified lookup keyed by 15-char ICN.

    Each MTF sheet is selected by its NPI mapping.  ICNs are zero-padded
    to 15 characters to compensate for Excel stripping leading zeros.
    A 'Pharmacy NPI' column is added so the caller can join on both ICN
    and NPI when needed.

    Parameters:
        source: Path to the Beacon full-load .xlsx (contains MTF sheets).
        columns: Extra columns to load from each MTF sheet alongside ICN.
                 Defaults to ["Rx Num", "Fill Num"].

    Returns:
        DataFrame indexed by the 15-char ICN with the requested columns
        plus Pharmacy NPI.
    """
    if columns is None:
        columns = ["Rx Num", "Fill Num"]

    # Always need ICN for the join key
    usecols: list[str] = ["ICN", *columns]
    parts: list[pd.DataFrame] = []

    for npi, sheet_name in NPI_TO_SHEET.items():
        mtf: pd.DataFrame = pd.read_excel(
            source,
            sheet_name=sheet_name,
            usecols=usecols,
            engine="openpyxl",
            dtype="string",
        )
        mtf.columns = mtf.columns.str.strip()
        # Excel drops leading zeros from numeric-looking strings;
        # zero-pad back to the canonical widths used in sheet 1
        mtf["ICN"] = mtf["ICN"].str.zfill(15)
        if "Rx Num" in mtf.columns:
            mtf["Rx Num"] = mtf["Rx Num"].str.zfill(12)
        # Tag each row so callers can trace it back to its source sheet
        mtf["Pharmacy NPI"] = npi
        parts.append(mtf)

    # Merge the four sheets into one lookup, keyed by the normalised ICN
    combined: pd.DataFrame = pd.concat(parts, ignore_index=True)
    combined = combined.set_index("ICN")
    return combined


def enrich_with_mtf(
    retained: pd.DataFrame,
    mtf_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """Merge MTF columns into the retained DataFrame by ICN.

    Parameters:
        retained: Filtered DataFrame with at least an ICN column.
        mtf_lookup: Lookup table from build_mtf_lookup(), indexed by ICN.

    Returns:
        A copy of *retained* with the MTF columns appended.
    """
    # Only pull data columns; Pharmacy NPI is a routing key, not enrichment data
    mtf_cols: list[str] = [
        c for c in mtf_lookup.columns if c != "Pharmacy NPI"
    ]

    # Start with empty columns so unmatched rows get NA, not KeyError
    enriched: pd.DataFrame = retained.copy()
    for col in mtf_cols:
        enriched[col] = pd.NA

    # Filter to retained ICNs that exist in the MTF lookup
    found: pd.Series = enriched["ICN"].isin(mtf_lookup.index)
    matched_icns: pd.Series = enriched.loc[found, "ICN"]

    # Copy values by aligned position — .values avoids index-alignment
    # issues between the retained DataFrame and the MTF lookup
    for col in mtf_cols:
        enriched.loc[found, col] = mtf_lookup.loc[
            matched_icns.values, col
        ].values

    return enriched


def load_transaction_descriptions(path: Path) -> dict[str, str]:
    """Load transaction code descriptions from the lookup spreadsheet.

    Codes are zero-padded to 3 characters so they match the format
    used in the Beacon full-load first sheet.

    Parameters:
        path: Path to the transaction codes .xlsx file.

    Returns:
        Dict mapping 3-char transaction code to its Description string.
    """
    df: pd.DataFrame = pd.read_excel(
        path,
        usecols=["Code", "Description"],
        engine="openpyxl",
        dtype="string",
    )
    df.columns = df.columns.str.strip()
    # Codes in lookup are unpadded ("1"); full-load uses "001"
    df["Code"] = df["Code"].str.zfill(3)
    return dict(zip(df["Code"], df["Description"]))


def enrich_with_transaction_desc(
    df: pd.DataFrame,
    descriptions: dict[str, str],
) -> pd.DataFrame:
    """Add a Transaction Description column by matching Transaction Code.

    Parameters:
        df: DataFrame with a Transaction Code column.
        descriptions: Mapping from 3-char code to description string.

    Returns:
        A copy of *df* with Transaction Description inserted after
        Transaction Code.
    """
    enriched: pd.DataFrame = df.copy()
    enriched["Transaction Description"] = enriched["Transaction Code"].map(
        descriptions,
    )
    # Place the new column right after Transaction Code
    code_pos: int = enriched.columns.get_loc("Transaction Code") + 1
    col: pd.Series = enriched.pop("Transaction Description")
    enriched.insert(code_pos, "Transaction Description", col)
    return enriched


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


def write_filtered_excel(df: pd.DataFrame, path: Path) -> None:
    """Write the retained rows to a new Excel file, preserving all columns.

    Parameters:
        df: Enriched DataFrame (retained rows + MTF columns).
        path: Output .xlsx file path.
    """
    # index=False keeps the output clean — pandas row numbers aren't meaningful
    df.to_excel(path, index=False, engine="openpyxl")


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
    df: pd.DataFrame = load_transactions(input_path)
    print(f"  {len(df)} data rows loaded.")

    all_xrefs: set[str] = set(df["Xref"].dropna())

    print("Building cross-reference chains ...")
    chains: list[Chain] = build_chains(df, all_xrefs)
    print(f"  {len(chains)} chains found.")

    retained: pd.DataFrame = get_retained_df(df, all_xrefs)
    print(f"  {len(retained)} rows retained, {len(df) - len(retained)} discarded.")

    print(f"Writing chain report to {chain_report} ...")
    write_chain_report(chains, len(df), len(retained), chain_report)

    print(f"Writing retained ICNs report to {retained_icns} ...")
    write_retained_icns_report(chains, retained_icns)

    print("Loading MTF lookup tables ...")
    mtf_lookup: pd.DataFrame = build_mtf_lookup(input_path)
    print(f"  {len(mtf_lookup)} MTF entries loaded.")

    print("Enriching retained rows with Rx Num / Fill Num ...")
    enriched: pd.DataFrame = enrich_with_mtf(retained, mtf_lookup)
    matched: int = int(enriched["Rx Num"].notna().sum())
    print(f"  {matched}/{len(enriched)} rows matched.")

    tx_codes_path: Path = input_path.parent / TRANSACTION_CODES_NAME
    if tx_codes_path.is_file():
        print(f"Loading transaction descriptions from {tx_codes_path.name} ...")
        descriptions: dict[str, str] = load_transaction_descriptions(tx_codes_path)
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
