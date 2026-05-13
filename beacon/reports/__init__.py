"""Text report writers for the Beacon pipeline.

Each submodule owns one report family so unrelated formatting changes do
not force edits to a single monolithic file:

+------------------------+----------------------------------------------+
| Submodule              | Writer                                       |
+========================+==============================================+
| ``chains``             | ``write_chain_report`` /                     |
|                        | ``write_retained_icns_report``               |
| ``analytics``          | ``write_analytics_report``                   |
| ``duplicates``         | ``write_duplicate_reports``                  |
| ``verity_coverage``    | ``write_verity_coverage_report``             |
| ``verity_matches``     | ``write_verity_matches_report``              |
+------------------------+----------------------------------------------+

All public writers are re-exported here so existing callers can continue
to ``from beacon.reports import write_chain_report`` without knowing the
internal layout.
"""

from beacon.reports.analytics import write_analytics_report
from beacon.reports.chains import write_chain_report, write_retained_icns_report
from beacon.reports.duplicates import write_duplicate_reports
from beacon.reports.verity_coverage import write_verity_coverage_report
from beacon.reports.verity_matches import (
    write_verity_matches_duplicates_report,
    write_verity_matches_report,
)

__all__ = [
    "write_analytics_report",
    "write_chain_report",
    "write_duplicate_reports",
    "write_retained_icns_report",
    "write_verity_coverage_report",
    "write_verity_matches_duplicates_report",
    "write_verity_matches_report",
]
