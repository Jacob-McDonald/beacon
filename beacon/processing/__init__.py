"""ICN chain logic, MTF enrichment, and Excel export.

Split into submodules by concern (mirrors :mod:`beacon.reports`):

- :mod:`beacon.processing.chains` — Chain / ChainLink model, chain build,
  retained-row filter.
- :mod:`beacon.processing.loaders` — Excel readers for the full-load
  workbook, MTF sheets, Verity claims rollup, and supplement file.
- :mod:`beacon.processing.enrichment` — DataFrame-to-DataFrame merges
  that append MTF data, transaction descriptions, and supplement columns.
- :mod:`beacon.processing.writers` — Excel writer for the filtered
  output workbook.

Every public symbol is re-exported here so external callers can keep
importing via ``from beacon.processing import ...`` regardless of which
submodule actually defines the name.
"""

from beacon.processing.chains import (
    Chain,
    ChainLink,
    build_chains,
    get_retained_df,
)
from beacon.processing.enrichment import (
    enrich_with_mtf,
    enrich_with_transaction_desc,
)
from beacon.processing.loaders import (
    build_mtf_lookup,
    load_transactions,
    load_verity_claims_submission,
)
from beacon.processing.writers import write_filtered_excel

__all__ = [
    "Chain",
    "ChainLink",
    "build_chains",
    "build_mtf_lookup",
    "enrich_with_mtf",
    "enrich_with_transaction_desc",
    "get_retained_df",
    "load_transactions",
    "load_verity_claims_submission",
    "write_filtered_excel",
]
