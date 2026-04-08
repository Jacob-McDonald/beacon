"""Fixed strings and lookup tables for Beacon processing."""

from __future__ import annotations

# Columns required from sheet 1 of the full-load workbook
REQUIRED_COLUMNS: list[str] = ["ICN", "Xref", "Transaction Code", "Pharmacy NPI"]

# Default output filenames (resolved against the chosen output directory)
CHAIN_REPORT_NAME: str = "Xref_Chain_Report.txt"
RETAINED_ICNS_NAME: str = "ICN_Retained.txt"
FILTERED_NAME: str = "BeaconT2.xlsx"
TRANSACTION_CODES_NAME: str = "BeaconMFPTransactionCodes.xlsx"
ANALYTICS_NAME: str = "Beacon_Analytics.txt"

# Pharmacy NPI → MTF sheet name in the full-load workbook
NPI_TO_SHEET: dict[str, str] = {
    "1073835591": "MTF - Specialty",
    "1194345199": "MTF - CDA",
    "1235986290": "MTF - Hayden",
    "1487401451": "MTF - Post Falls",
}
