"""Verity claims overlap: (NPI, Rx, Fill) triple membership against the enriched Beacon frame.

A *hit* is defined per Beacon row: the row is a hit when at least one Verity
claims submission row shares the same ``(Pharmacy NPI, Rx Num, Fill Num)``
triple, keyed as follows:

+----------------+---------------------------+
| Beacon column  | Verity column             |
+================+===========================+
| Pharmacy NPI   | Service Provider ID       |
| Rx Num         | Rx Number                 |
| Fill Num       | Fill Number               |
+----------------+---------------------------+

Beacon rows whose Rx or Fill values cannot be parsed (missing, blank, or
non-numeric) count as misses: there is no well-defined key for them, so
by construction they cannot match any Verity row.

Join-key normalisation lives in :mod:`beacon.keys` so the same rules
apply to every comparison in the pipeline.

The module exposes three entry points:

- :func:`verity_hit_mask` — per-row boolean mask (True = Beacon row is a hit).
- :func:`verity_coverage_stats` — aggregate counts built on top of the mask.
- :func:`verity_npi_rx_pair_set` — (NPI, Rx) set used to diagnose misses that
  probably differ only by Fill Number.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from beacon.constants import (
    BEACON_COL_FILL_NUM,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_RX_NUM,
    VERITY_CLAIMS_FILL_COL,
    VERITY_CLAIMS_NPI_COL,
    VERITY_CLAIMS_RX_COL,
)
from beacon.keys import (
    fill_key_series,
    npi_key,
    npi_key_series,
    rx_key,
    rx_key_series,
)


@dataclass(frozen=True, slots=True)
class VerityCoverageStats:
    """Result of comparing the enriched Beacon frame against Verity claims.

    Attributes:
        beacon_row_count: Total rows in the enriched Beacon frame.
        hits: Beacon rows whose (NPI, Rx, Fill) triple appears in Verity.
        misses: ``beacon_row_count - hits``.
        hit_rate: ``hits / beacon_row_count`` (``0.0`` when the frame is empty).
    """

    beacon_row_count: int
    hits: int
    misses: int
    hit_rate: float


def _triple_set(
    df: pd.DataFrame,
    npi_col: str,
    rx_col: str,
    fill_col: str,
) -> set[tuple[str, str, int]]:
    """Build the set of ``(NPI, Rx, Fill)`` triples from *df*.

    Rows with any missing or unparseable key component are skipped; they
    cannot contribute a valid join key.
    """
    npi_series: pd.Series = npi_key_series(df[npi_col])
    rx_series: pd.Series = rx_key_series(df[rx_col])
    fill_series: pd.Series = fill_key_series(df[fill_col])

    valid: pd.Series = (
        npi_series.ne("") & rx_series.ne("") & fill_series.notna()
    )
    keyed: pd.DataFrame = pd.DataFrame(
        {
            "npi": npi_series[valid].astype(str),
            "rx": rx_series[valid].astype(str),
            "fill": fill_series[valid].astype("int64"),
        },
    )
    return set(keyed.itertuples(index=False, name=None))


def _pair_set(
    df: pd.DataFrame,
    npi_col: str,
    rx_col: str,
) -> set[tuple[str, str]]:
    """Build the set of ``(NPI, Rx)`` pairs from *df* (Fill ignored)."""
    npi_series: pd.Series = npi_key_series(df[npi_col])
    rx_series: pd.Series = rx_key_series(df[rx_col])

    valid: pd.Series = npi_series.ne("") & rx_series.ne("")
    keyed: pd.DataFrame = pd.DataFrame(
        {
            "npi": npi_series[valid].astype(str),
            "rx": rx_series[valid].astype(str),
        },
    )
    return set(keyed.itertuples(index=False, name=None))


def verity_hit_mask(
    enriched: pd.DataFrame,
    verity_df: pd.DataFrame,
) -> pd.Series:
    """Per-row boolean mask aligned with *enriched*'s index.

    ``True`` means the Beacon row's ``(Pharmacy NPI, Rx Num, Fill Num)``
    triple is present in the Verity claims submission frame.

    Beacon rows with an unparseable key component are ``False`` (they can
    never form a valid join key).
    """
    verity_triples: set[tuple[str, str, int]] = _triple_set(
        verity_df,
        npi_col=VERITY_CLAIMS_NPI_COL,
        rx_col=VERITY_CLAIMS_RX_COL,
        fill_col=VERITY_CLAIMS_FILL_COL,
    )

    beacon_npi: pd.Series = npi_key_series(enriched[BEACON_COL_PHARMACY_NPI])
    beacon_rx: pd.Series = rx_key_series(enriched[BEACON_COL_RX_NUM])
    beacon_fill: pd.Series = fill_key_series(enriched[BEACON_COL_FILL_NUM])

    valid: pd.Series = beacon_npi.ne("") & beacon_rx.ne("") & beacon_fill.notna()
    result: pd.Series = pd.Series(False, index=enriched.index, name="verity_hit")
    if not verity_triples or not bool(valid.any()):
        return result

    # Vectorised membership check: build a MultiIndex from the valid-row
    # keys and test against a MultiIndex view of the Verity triple set.
    verity_idx: pd.MultiIndex = pd.MultiIndex.from_tuples(
        verity_triples, names=["npi", "rx", "fill"],
    )
    beacon_idx: pd.MultiIndex = pd.MultiIndex.from_arrays(
        [
            beacon_npi[valid].astype(str).to_numpy(),
            beacon_rx[valid].astype(str).to_numpy(),
            beacon_fill[valid].astype("int64").to_numpy(),
        ],
        names=["npi", "rx", "fill"],
    )
    result.loc[valid] = beacon_idx.isin(verity_idx)
    return result


def verity_npi_rx_pair_set(verity_df: pd.DataFrame) -> set[tuple[str, str]]:
    """Build the ``(Service Provider ID, Rx Number)`` pair set from Verity.

    Used to diagnose misses that would otherwise match on NPI and Rx but
    differ only on Fill Number.
    """
    return _pair_set(
        verity_df,
        npi_col=VERITY_CLAIMS_NPI_COL,
        rx_col=VERITY_CLAIMS_RX_COL,
    )


def beacon_npi_rx_pair(row: pd.Series) -> tuple[str, str] | None:
    """``(NPI, Rx)`` key for a Beacon row; ``None`` if either side is blank."""
    npi: str = npi_key(row.get(BEACON_COL_PHARMACY_NPI))
    rx: str = rx_key(row.get(BEACON_COL_RX_NUM))
    if npi == "" or rx == "":
        return None
    return (npi, rx)


def verity_coverage_stats(
    enriched: pd.DataFrame,
    verity_df: pd.DataFrame,
) -> VerityCoverageStats:
    """Count how many enriched Beacon rows appear in the Verity claims file.

    Parameters:
        enriched: Enriched Beacon frame with columns ``Pharmacy NPI``,
                  ``Rx Num``, ``Fill Num``.
        verity_df: Verity claims submission frame with columns
                   ``Service Provider ID``, ``Rx Number``, ``Fill Number``
                   (as returned by
                   :func:`beacon.processing.load_verity_claims_submission`).

    Returns:
        A :class:`VerityCoverageStats` with total row count, hits, misses,
        and hit rate.
    """
    mask: pd.Series = verity_hit_mask(enriched, verity_df)
    total: int = len(enriched)
    hits: int = int(mask.sum())
    misses: int = total - hits
    hit_rate: float = (hits / total) if total > 0 else 0.0
    return VerityCoverageStats(
        beacon_row_count=total,
        hits=hits,
        misses=misses,
        hit_rate=hit_rate,
    )
