"""Beacon package — ICN chain deduplication, MTF enrichment, and analytics.

This ``__init__`` re-exports a small, curated public API so callers can
import the everyday names directly from ``beacon``::

    from beacon import run, PipelineConfig

Anything outside this curated surface is still reachable through the
submodule it lives in — e.g. ``from beacon.keys import rx_key_series``
or ``from beacon.verity_matches import process_verity_matches``.  The
short ``__all__`` keeps wildcard imports tidy and signals which names
are considered the supported entry points.

Submodules:

- :mod:`beacon.constants` — fixed strings, NPI maps, transaction labels,
  and the ``PROJECT_ROOT`` anchor used for default file paths.
- :mod:`beacon.keys` — (ICN, NPI, Rx, Fill) join-key normalisation.
- :mod:`beacon.pipeline` — top-level :func:`run` and config / result types.
- :mod:`beacon.processing` — load, chain-build, enrichment, Excel export.
- :mod:`beacon.reports` — text-report writers (chains, analytics, dupes,
  Verity coverage, Verity_Matches).
- :mod:`beacon.verity_coverage` — Verity claims overlap statistics.
- :mod:`beacon.verity_matches` — Verity_Matches filtering, dupe audit,
  and YES/NO enrichment of the Beacon frame.
"""

from __future__ import annotations

from beacon.constants import BEACON_PHARMACY_NPIS, NPI_TO_SHEET
from beacon.keys import canonical_icn_series
from beacon.pipeline import PipelineConfig, PipelineResult, run
from beacon.processing import (
    Chain,
    ChainLink,
    build_chains,
    build_mtf_lookup,
    enrich_with_mtf,
    get_retained_df,
    load_transactions,
    write_filtered_excel,
)

__all__: list[str] = [
    "BEACON_PHARMACY_NPIS",
    "Chain",
    "ChainLink",
    "NPI_TO_SHEET",
    "PipelineConfig",
    "PipelineResult",
    "build_chains",
    "build_mtf_lookup",
    "canonical_icn_series",
    "enrich_with_mtf",
    "get_retained_df",
    "load_transactions",
    "run",
    "write_filtered_excel",
]
