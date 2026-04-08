"""List all filtered (retained) ICNs grouped by pharmacy location."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon._paths import PROJECT_ROOT
from beacon.pipeline import NPI_TO_SHEET

INPUT_FILE: Path = PROJECT_ROOT / "Beacon_Full_Load.xlsx"
OUTPUT_FILE: Path = PROJECT_ROOT / "ICN_By_Location.txt"


def main() -> None:
    print(f"Loading {INPUT_FILE.name} ...")

    sheet1: pd.DataFrame = pd.read_excel(
        INPUT_FILE,
        sheet_name=0,
        usecols=["ICN", "Xref", "Pharmacy NPI"],
        engine="openpyxl",
        dtype="string",
    )
    sheet1.columns = sheet1.columns.str.strip()

    all_xrefs: set[str] = set(sheet1["Xref"].dropna())
    retained: pd.DataFrame = sheet1[~sheet1["ICN"].isin(all_xrefs)].copy()
    print(f"  {len(retained)} retained rows\n")

    lines: list[str] = []

    for npi, location in NPI_TO_SHEET.items():
        subset: pd.DataFrame = retained[retained["Pharmacy NPI"] == npi]
        icns: list[str] = sorted(subset["ICN"].tolist())

        lines.append(f"{location}  (NPI {npi})    Count: {len(icns)}")
        lines.append("=" * 60)
        for icn in icns:
            lines.append(f"  {icn}")
        lines.append("")
        lines.append("")

        print(f"  {location:<20s}  {len(icns):>5} ICNs")

    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWritten to {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
