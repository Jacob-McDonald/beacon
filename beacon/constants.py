"""Fixed strings and lookup tables for Beacon processing.

All sequences in this module are immutable (``tuple`` / ``frozenset``) so
they cannot be mutated by callers.  The two module-level mappings
(:data:`TRANSACTION_CODE_DESCRIPTIONS`, :data:`NPI_TO_SHEET`) are exposed
through :class:`types.MappingProxyType` views so callers see read-only
``Mapping`` semantics without losing ``dict``-style access.
Column-header constants are exposed individually for explicit imports
and are also grouped into ``REQUIRED_COLUMNS`` / ``VERITY_CLAIMS_COLUMNS``
for bulk ``usecols=`` calls into ``pd.read_excel``.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping

# ---------------------------------------------------------------------------
# Project root — used to anchor default file paths (e.g. the default
# input workbook resolved by the CLI / verify_mtf when no path is given).
# ---------------------------------------------------------------------------

# beacon/constants.py -> beacon/ -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Beacon workbook column headers (sheet 1 + MTF sheets after join).
# ---------------------------------------------------------------------------

BEACON_COL_ICN: str = "ICN"
BEACON_COL_XREF: str = "Xref"
BEACON_COL_TXN_CODE: str = "Transaction Code"
BEACON_COL_TXN_DESC: str = "Transaction Description"
BEACON_COL_PHARMACY_NPI: str = "Pharmacy NPI"
BEACON_COL_BASIS_OF_PRICE: str = "Basis of Price"
BEACON_COL_RX_NUM: str = "Rx Num"
BEACON_COL_FILL_NUM: str = "Fill Num"

# Columns required from sheet 1 of the full-load workbook.
REQUIRED_COLUMNS: tuple[str, ...] = (
    BEACON_COL_ICN,
    BEACON_COL_XREF,
    BEACON_COL_TXN_CODE,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_BASIS_OF_PRICE,
)

# ---------------------------------------------------------------------------
# Verity claims submission workbook (e.g. Oct_2025–Apr_2026 rollup).
# Only the three columns needed for NPI/Rx/Fill overlap are loaded —
# date and financial fields are ignored.
# ---------------------------------------------------------------------------

VERITY_CLAIMS_SUBMISSION_SHEET: str = "Verity_Claims_Submission"
VERITY_CLAIMS_NPI_COL: str = "Service Provider ID"
VERITY_CLAIMS_RX_COL: str = "Rx Number"
VERITY_CLAIMS_FILL_COL: str = "Fill Number"
VERITY_CLAIMS_COLUMNS: tuple[str, ...] = (
    VERITY_CLAIMS_NPI_COL,
    VERITY_CLAIMS_RX_COL,
    VERITY_CLAIMS_FILL_COL,
)

# ---------------------------------------------------------------------------
# Output artifact filenames (basenames only; join with output or input dir).
# ---------------------------------------------------------------------------

# Default input workbook filename, resolved relative to the project root
# when no explicit path is supplied on the CLI or in verify_mtf.
DEFAULT_INPUT_FILENAME: str = "Beacon_Full_Load.xlsx"

XREF_CHAIN_REPORT_FILE: str = "Xref_Chain_Report.txt"
RETAINED_ICNS_REPORT_FILE: str = "ICN_Retained.txt"
FILTERED_EXCEL_OUTPUT_FILE: str = "Beacon_Filtered.xlsx"
BEACON_ANALYTICS_REPORT_FILE: str = "Beacon_Analytics.txt"
DUPLICATE_PATTERNS_REPORT_FILE: str = "Rx_Fill_Duplicate_Patterns.txt"
DUPLICATE_GROUPS_REPORT_FILE: str = "Rx_Fill_Duplicate_Groups.txt"
VERITY_COVERAGE_REPORT_FILE: str = "Verity_Coverage.txt"
VERITY_MATCHES_REPORT_FILE: str = "Verity_Matches.txt"
VERITY_MATCHES_DUPLICATES_REPORT_FILE: str = "Verity_Matches_Duplicates.txt"

# Subfolder name for all text reports (relative to the output directory).
REPORTS_SUBDIR: str = "reports"

# ---------------------------------------------------------------------------
# Verity_Matches workbook: per-month or single-range exports with 67 columns.
# Only four headers matter for the pharmacy filter + (NPI, Rx, Fill) join.
# ---------------------------------------------------------------------------

VERITY_MATCHES_SHEET: str = "New Matches"
VERITY_MATCHES_MATCH_NPI_COL: str = "Match NPI"
VERITY_MATCHES_ELIGIBLE_COL: str = "Eligible"
VERITY_MATCHES_RX_COL: str = "Rx Number"
VERITY_MATCHES_FILL_COL: str = "Disp Fill #"

# Name of the YES/NO column added to the enriched Beacon frame when
# ``-m`` / ``--verity-matches`` is supplied.
BEACON_COL_VERITY_MATCHES: str = "Verity_Matches"

# Folder-scan pattern and filtered-output basename for Verity_Matches.
VERITY_MATCHES_FILE_GLOB: str = "*_Verity_Matches.xlsx"
VERITY_MATCHES_FILTERED_BASENAME: str = "Verity_Matches_Filtered.xlsx"

# Pipeline-internal sentinel column that tags each filtered Verity_Matches
# row with its originating workbook filename.  Underscore-prefixed so the
# xlsx writer can strip it before exporting the filtered workbook.
_SOURCE_FILE_COL: str = "_Source_File"

# Curated subset of Verity_Matches columns shown in the duplicate-group
# comparison report.  Ordering is display-order, not load-order.  The
# source-file sentinel is first so the reader can tell at a glance
# whether a group spans multiple monthly files.
VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS: tuple[str, ...] = (
    _SOURCE_FILE_COL,
    "MatchId",
    "Match Type",
    "Match Pharmacy",
    VERITY_MATCHES_MATCH_NPI_COL,
    VERITY_MATCHES_ELIGIBLE_COL,
    VERITY_MATCHES_RX_COL,
    VERITY_MATCHES_FILL_COL,
    "Disp Fill Date",
    "Rx Written Date",
    "Matched Date",
    "Matched By",
    "Activity",
    "Activity Date",
    "Disp Qty",
    "Allocated Qty",
    "Total Paid",
    "NDC",
    "ItemName",
    "Provider NPI",
    "Provider",
    "Patient Last Initial",
    "Patient First",
    "Enc Id",
    "MRN",
    "Unique Claim ID",
)

# ---------------------------------------------------------------------------
# MFP transaction codes → short labels (keys are 3-char zero-padded,
# matching the normalised values on sheet 1).
# ---------------------------------------------------------------------------

_TRANSACTION_CODE_DESCRIPTIONS: dict[str, str] = {
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
TRANSACTION_CODE_DESCRIPTIONS: Mapping[str, str] = MappingProxyType(
    _TRANSACTION_CODE_DESCRIPTIONS,
)

# ---------------------------------------------------------------------------
# Pharmacy NPI → MTF sheet name in the full-load workbook.
# ---------------------------------------------------------------------------

_NPI_TO_SHEET: dict[str, str] = {
    "1073835591": "MTF - Specialty",
    "1194345199": "MTF - CDA",
    "1235986290": "MTF - Hayden",
    "1487401451": "MTF - Post Falls",
}
NPI_TO_SHEET: Mapping[str, str] = MappingProxyType(_NPI_TO_SHEET)

# Subset of NPIs used across Beacon MTF / Verity_Matches filtering.
BEACON_PHARMACY_NPIS: frozenset[str] = frozenset(_NPI_TO_SHEET.keys())
