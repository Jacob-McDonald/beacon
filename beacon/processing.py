"""ICN chain logic, MTF enrichment, and Excel export.

Text reports live in :mod:`beacon.reports`.  :mod:`beacon.pipeline` wires
everything together.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pandas as pd

from beacon.constants import NPI_TO_SHEET, REQUIRED_COLUMNS


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


def write_filtered_excel(df: pd.DataFrame, path: Path) -> None:
    """Write the retained rows to a new Excel file, preserving all columns.

    Parameters:
        df: Enriched DataFrame (retained rows + MTF columns).
        path: Output .xlsx file path.
    """
    # index=False keeps the output clean — pandas row numbers aren't meaningful
    df.to_excel(path, index=False, engine="openpyxl")
