"""Excel readers for the Beacon pipeline.

Each loader wraps ``pd.read_excel`` with path-existence checks, a
dtype-neutral string policy that preserves leading zeros, and sheet-
specific column normalisation.  Consumers receive a DataFrame that is
ready for chain building (:mod:`beacon.processing.chains`) or
enrichment (:mod:`beacon.processing.enrichment`); no further cleanup
should be needed at the call site.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_COL_FILL_NUM,
    BEACON_COL_ICN,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_RX_NUM,
    BEACON_COL_XREF,
    NPI_TO_SHEET,
    REQUIRED_COLUMNS,
    VERITY_CLAIMS_COLUMNS,
    VERITY_CLAIMS_SUBMISSION_SHEET,
)
from beacon.keys import canonical_icn_series, rx_key_series

log: logging.Logger = logging.getLogger(__name__)


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
        # dtype="string" keeps ICNs as text so leading zeros are preserved.
        # Reading without usecols and validating column names ourselves
        # produces a friendlier error than pandas' generic ValueError when
        # a required column is missing.
        df: pd.DataFrame = pd.read_excel(
            path, sheet_name=0, engine="openpyxl", dtype="string",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to read Excel file: {path}") from exc

    df.columns = df.columns.str.strip()

    missing: list[str] = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required column(s) on sheet 1: {missing}. "
            f"Found columns: {list(df.columns)}",
        )

    df = df.loc[:, list(REQUIRED_COLUMNS)].copy()

    # Normalise ICN / Xref to the 15-char canonical form at the door so
    # every downstream step (chain build, MTF merge, verification) sees
    # the same keys.  Prevents silent drops when Excel trims leading
    # zeros on one sheet but not another.  ``canonical_icn_series``
    # also coerces whitespace-only cells to NA so blanks don't silently
    # pad to "000000000000000" and participate in joins as a valid ICN.
    df[BEACON_COL_ICN] = canonical_icn_series(df[BEACON_COL_ICN])
    df[BEACON_COL_XREF] = canonical_icn_series(df[BEACON_COL_XREF])
    return df


def load_verity_claims_submission(path: Path) -> pd.DataFrame:
    """Load the Verity claims submission join columns from the workbook.

    Reads the ``Verity_Claims_Submission`` sheet (contract / rebate export)
    and keeps only the three columns needed for NPI/Rx/Fill overlap:
    ``Service Provider ID``, ``Rx Number``, ``Fill Number``.

    All values are loaded as nullable strings; downstream consumers
    normalise per-column (zero-padded Rx keys, integer fill numbers,
    etc.) so the loader stays dtype-neutral.

    Parameters:
        path: Path to the Verity rollup ``.xlsx`` file.

    Returns:
        DataFrame with the three join columns and a 0-based pandas index.

    Raises:
        FileNotFoundError: If the path does not exist or is not a file.
        RuntimeError: If the Excel file cannot be read.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Path is not a file: {path}")

    try:
        df: pd.DataFrame = pd.read_excel(
            path,
            sheet_name=VERITY_CLAIMS_SUBMISSION_SHEET,
            usecols=list(VERITY_CLAIMS_COLUMNS),
            engine="openpyxl",
            dtype="string",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to read Verity claims file: {path}") from exc

    df.columns = df.columns.str.strip()
    return df


def build_mtf_lookup(
    source: Path,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load all MTF sheets and return a unified lookup keyed by (ICN, NPI).

    Each MTF sheet is selected by its NPI mapping.  ICNs are zero-padded
    to 15 characters to compensate for Excel stripping leading zeros.
    The result is keyed by both ICN and Pharmacy NPI so the downstream
    merge in :func:`enrich_with_mtf` cannot fan out rows when the same
    ICN appears under more than one pharmacy.  Duplicate (ICN, NPI) rows
    within a single MTF sheet are dropped with a warning.

    Parameters:
        source: Path to the Beacon full-load .xlsx (contains MTF sheets).
        columns: Extra columns to load from each MTF sheet alongside ICN.
                 Defaults to ``["Rx Num", "Fill Num"]``.

    Returns:
        DataFrame with the requested data columns plus Pharmacy NPI,
        indexed by ``(ICN, Pharmacy NPI)``.
    """
    if columns is None:
        columns = [BEACON_COL_RX_NUM, BEACON_COL_FILL_NUM]

    # Always need ICN for the join key
    usecols: list[str] = [BEACON_COL_ICN, *columns]
    parts: list[pd.DataFrame] = []

    # Open the workbook once and reuse the handle for every sheet — avoids
    # reparsing the entire .xlsx (the dominant cost) on every NPI.
    with pd.ExcelFile(source, engine="openpyxl") as xls:
        for npi, sheet_name in NPI_TO_SHEET.items():
            try:
                mtf: pd.DataFrame = pd.read_excel(
                    xls, sheet_name=sheet_name, usecols=usecols, dtype="string",
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to read MTF sheet {sheet_name!r} from {source}",
                ) from exc
            mtf.columns = mtf.columns.str.strip()
            # Canonicalise the join keys the same way load_transactions does
            # so both sides of the merge use identical strings.  Empty ICNs
            # become NA (dropped by set_index below would collide otherwise).
            mtf[BEACON_COL_ICN] = canonical_icn_series(mtf[BEACON_COL_ICN])
            if BEACON_COL_RX_NUM in mtf.columns:
                mtf[BEACON_COL_RX_NUM] = rx_key_series(mtf[BEACON_COL_RX_NUM])
            # Tag each row so callers can trace it back to its source sheet
            mtf[BEACON_COL_PHARMACY_NPI] = npi
            parts.append(mtf)

    combined: pd.DataFrame = pd.concat(parts, ignore_index=True)

    # Defend against duplicate (ICN, NPI) rows within a single MTF sheet —
    # they would fan out the left merge in enrich_with_mtf and inflate
    # retained row counts.
    dupes: pd.Series = combined.duplicated(
        subset=[BEACON_COL_ICN, BEACON_COL_PHARMACY_NPI],
    )
    if dupes.any():
        log.warning(
            "Dropping %d duplicate (ICN, NPI) row(s) from the MTF lookup.",
            int(dupes.sum()),
        )
        combined = combined[~dupes].copy()

    return combined.set_index([BEACON_COL_ICN, BEACON_COL_PHARMACY_NPI])

