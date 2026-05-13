"""DataFrame-to-DataFrame merges that decorate the working Beacon frame.

Every function takes the current working frame as the first argument
and returns a copy with additional columns.  None of them touch the
filesystem — path-based inputs are loaded upstream by
:mod:`beacon.processing.loaders`.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from beacon.constants import (
    BEACON_COL_ICN,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_TXN_CODE,
    BEACON_COL_TXN_DESC,
)


def enrich_with_mtf(
    enriched: pd.DataFrame,
    mtf_lookup: pd.DataFrame,
) -> pd.DataFrame:
    """Merge MTF columns into the working DataFrame on (ICN, Pharmacy NPI).

    Uses a left merge so every input row is preserved.  Joining on the
    composite key (rather than ICN alone) prevents row explosions if the
    same ICN ever appears under more than one pharmacy in the MTF
    lookup.

    Parameters:
        enriched: Current working Beacon frame with ICN and Pharmacy NPI
                  columns.
        mtf_lookup: Lookup table from :func:`build_mtf_lookup`, indexed by
                    ``(ICN, Pharmacy NPI)``.

    Returns:
        A copy of *enriched* with the MTF data columns appended.
    """
    return enriched.merge(
        mtf_lookup,
        left_on=[BEACON_COL_ICN, BEACON_COL_PHARMACY_NPI],
        right_index=True,
        how="left",
    )


def enrich_with_transaction_desc(
    enriched: pd.DataFrame,
    descriptions: Mapping[str, str],
) -> pd.DataFrame:
    """Add a Transaction Description column by matching Transaction Code.

    Parameters:
        enriched: Current working Beacon frame with a Transaction Code
                  column.
        descriptions: Mapping from 3-char code to description string.

    Returns:
        A copy of *enriched* with Transaction Description inserted after
        Transaction Code.
    """
    out: pd.DataFrame = enriched.copy()
    out[BEACON_COL_TXN_DESC] = out[BEACON_COL_TXN_CODE].map(dict(descriptions))
    # Place the new column right after Transaction Code
    code_pos: int = out.columns.get_loc(BEACON_COL_TXN_CODE) + 1
    col: pd.Series = out.pop(BEACON_COL_TXN_DESC)
    out.insert(code_pos, BEACON_COL_TXN_DESC, col)
    return out

