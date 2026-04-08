"""Verify that every retained ICN from sheet 1 exists in the matching MTF sheet."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon._paths import PROJECT_ROOT
from beacon.pipeline import NPI_TO_SHEET

INPUT_FILE: Path = PROJECT_ROOT / "Beacon_Full_Load.xlsx"


def normalise_icn(icn: str) -> str:
    """Zero-pad to 15 characters to undo Excel's leading-zero truncation."""
    return icn.zfill(15)


def verify(path: Path | None = None) -> bool:
    """Check that every retained ICN appears in the corresponding MTF sheet.

    Parameters:
        path: Path to the Beacon full-load .xlsx.  Defaults to
              Beacon_Full_Load.xlsx in the project root.

    Returns:
        True if every retained ICN was found in its MTF sheet, False otherwise.
    """
    source: Path = path or INPUT_FILE

    print(f"Loading {source.name} ...")

    sheet1: pd.DataFrame = pd.read_excel(
        source, sheet_name=0, engine="openpyxl", dtype="string",
    )
    sheet1.columns = sheet1.columns.str.strip()

    all_xrefs: set[str] = set(sheet1["Xref"].dropna())
    retained: pd.DataFrame = sheet1[~sheet1["ICN"].isin(all_xrefs)].copy()
    print(f"  {len(retained)} retained rows after chain filtering\n")

    total_checked: int = 0
    total_found: int = 0

    for npi, sheet_name in NPI_TO_SHEET.items():
        mtf: pd.DataFrame = pd.read_excel(
            source, sheet_name=sheet_name, engine="openpyxl", dtype="string",
        )
        mtf.columns = mtf.columns.str.strip()
        mtf_icns: set[str] = {normalise_icn(x) for x in mtf["ICN"].dropna()}

        subset: pd.DataFrame = retained[retained["Pharmacy NPI"] == npi]
        matched: pd.Series = subset["ICN"].apply(normalise_icn).isin(mtf_icns)
        n_found: int = int(matched.sum())
        n_missing: int = len(subset) - n_found
        total_checked += len(subset)
        total_found += n_found

        status: str = "ALL MATCH" if n_missing == 0 else f"{n_missing} MISSING"
        print(f"  NPI {npi} -> {sheet_name}")
        print(f"    retained: {len(subset):>5}   found: {n_found:>5}   {status}")

        if n_missing > 0:
            missing: list[str] = subset[~matched.values]["ICN"].head(5).tolist()
            print(f"    first missing: {missing}")

        print()

    passed: bool = total_found == total_checked
    print(f"TOTAL: {total_checked} checked, {total_found} found, "
          f"{total_checked - total_found} missing")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    return passed


if __name__ == "__main__":
    verify()
