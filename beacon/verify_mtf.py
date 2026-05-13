"""Verify that every retained ICN from sheet 1 exists in the matching MTF sheet."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_COL_ICN,
    BEACON_COL_PHARMACY_NPI,
    DEFAULT_INPUT_FILENAME,
    NPI_TO_SHEET,
    PROJECT_ROOT,
)
from beacon.processing import build_mtf_lookup, get_retained_df, load_transactions

INPUT_FILE: Path = PROJECT_ROOT / DEFAULT_INPUT_FILENAME

log: logging.Logger = logging.getLogger(__name__)


def verify(path: Path | None = None) -> bool:
    """Check that every retained ICN appears in the corresponding MTF sheet.

    Parameters:
        path: Path to the Beacon full-load .xlsx.  Defaults to
              ``Beacon_Full_Load.xlsx`` in the project root.

    Returns:
        ``True`` if every retained ICN was found in its MTF sheet,
        ``False`` otherwise.
    """
    source: Path = path or INPUT_FILE

    log.info("Loading %s ...", source.name)
    df: pd.DataFrame = load_transactions(source)
    retained: pd.DataFrame = get_retained_df(df)
    log.info("  %d retained rows after chain filtering", len(retained))

    # Reuse build_mtf_lookup so ICN canonicalisation has exactly one site.
    # columns=[] means we only load ICN per sheet — no Rx/Fill overhead.
    log.info("Loading MTF lookup tables ...")
    mtf_lookup: pd.DataFrame = build_mtf_lookup(source, columns=[])
    # The lookup is indexed by ``(ICN, Pharmacy NPI)``; pull the ICN level
    # per NPI directly from the index instead of going via groupby.
    icn_level: pd.Index = mtf_lookup.index.get_level_values(BEACON_COL_ICN)
    npi_level: pd.Index = mtf_lookup.index.get_level_values(BEACON_COL_PHARMACY_NPI)
    mtf_icns_by_npi: dict[str, set[str]] = {
        npi: set(icn_level[npi_level == npi].dropna())
        for npi in NPI_TO_SHEET
    }

    total_checked: int = 0
    total_found: int = 0

    for npi, sheet_name in NPI_TO_SHEET.items():
        mtf_icns: set[str] = mtf_icns_by_npi.get(npi, set())

        subset: pd.DataFrame = retained[retained[BEACON_COL_PHARMACY_NPI] == npi]
        # ICNs in `retained` are already canonicalised at load time, so no
        # per-row normalisation is needed here.
        matched: pd.Series = subset[BEACON_COL_ICN].isin(mtf_icns)
        n_found: int = int(matched.sum())
        n_missing: int = len(subset) - n_found
        total_checked += len(subset)
        total_found += n_found

        status: str = "ALL MATCH" if n_missing == 0 else f"{n_missing} MISSING"
        log.info("  NPI %s -> %s", npi, sheet_name)
        log.info(
            "    retained: %5d   found: %5d   %s",
            len(subset), n_found, status,
        )

        if n_missing > 0:
            missing: list[str] = subset[~matched.values][BEACON_COL_ICN].head(5).tolist()
            log.info("    first missing: %s", missing)

    passed: bool = total_found == total_checked
    log.info(
        "TOTAL: %d checked, %d found, %d missing",
        total_checked, total_found, total_checked - total_found,
    )
    log.info("Result: %s", "PASS" if passed else "FAIL")
    return passed


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(0 if verify() else 1)
