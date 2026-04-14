"""Fixed strings and lookup tables for Beacon processing."""

from __future__ import annotations

# Columns required from sheet 1 of the full-load workbook
REQUIRED_COLUMNS: list[str] = ["ICN", "Xref", "Transaction Code", "Pharmacy NPI"]

# Default artifact filenames (basename only; join with output or input dir)
XREF_CHAIN_REPORT_FILE: str = "Xref_Chain_Report.txt"
RETAINED_ICNS_REPORT_FILE: str = "ICN_Retained.txt"
FILTERED_EXCEL_OUTPUT_FILE: str = "Beacon_Filtered.xlsx"
BEACON_ANALYTICS_REPORT_FILE: str = "Beacon_Analytics.txt"

# MFP transaction code → short label (keys are 3-char zero-padded, matching sheet 1)
TRANSACTION_CODE_DESCRIPTIONS: dict[str, str] = {
    "001": "Original Claim",
    "002": "Adjustment Claim",
    "003": "Reversal Claim",
    "004": "Informational Claim",
    "005": "Withdrawal Notice",
    "009": "Claim is not MFP-eligible",
    "011": "Coordinate with Plan (Original Claim)",
    "012": "Coordinate with Plan (Adjustment Claim)",
    "013": "Coordinate with Plan (Reversal Claim)",
    "021": "Original Claim for Unenrolled Dispensing Entity",
    "022": "Adjustment Claim for Unenrolled Dispensing Entity",
    "023": "Reversal Claim for Unenrolled Dispensing Entity",
    "090": "Invalid MRA Response",
    "092": "Manufacturer-Initiated Adjustment Receipt",
    "099": "No claims for the selected drug of the primary manufacturer.",
}

# Pharmacy NPI → MTF sheet name in the full-load workbook
NPI_TO_SHEET: dict[str, str] = {
    "1073835591": "MTF - Specialty",
    "1194345199": "MTF - CDA",
    "1235986290": "MTF - Hayden",
    "1487401451": "MTF - Post Falls",
}
