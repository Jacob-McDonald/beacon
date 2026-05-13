"""Chain model and Xref graph build for the Beacon transaction data.

Exposes :class:`ChainLink` and :class:`Chain` (the typed records the rest
of the pipeline and every report module consume), plus
:func:`build_chains` (the graph walker) and :func:`get_retained_df` (the
post-chain row filter).  Pure in-memory / pandas; no filesystem access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

from beacon.constants import (
    BEACON_COL_ICN,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_TXN_CODE,
    BEACON_COL_XREF,
)

log: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One row in an Xref chain, with its transaction code attached.

    Attributes:
        index: 0-based row index in the source DataFrame (add 1 for the
               1-based spreadsheet row display).
        icn: 15-char canonical ICN of this row.
        xref: The ICN this row supersedes, or ``None`` for the chain
              origin (a row whose Xref cell is empty).
        txn_code: Transaction Code for this row, or ``""`` when the
                  source row lacks one.  Precomputed at build time so
                  downstream reports don't need a separate ICN->code map.
    """

    index: int
    icn: str
    xref: str | None
    txn_code: str


@dataclass(frozen=True, slots=True)
class Chain:
    """An ordered Xref chain from origin (oldest) to head (newest).

    Always contains at least two links; single-submission rows are not
    chains.  Metadata that downstream reports would otherwise recompute
    via lookup maps (origin NPI, terminal transaction codes) is captured
    at build time so callers stay focused on presentation.

    Attributes:
        links: Tuple of links from origin to head.  Length >= 2.
        origin_npi: Pharmacy NPI of the origin (first) link, or ``""``
                    when the source row had no NPI.
    """

    links: tuple[ChainLink, ...]
    origin_npi: str

    @property
    def depth(self) -> int:
        """Number of links in the chain (>= 2)."""
        return len(self.links)

    @property
    def origin(self) -> ChainLink:
        """The oldest link — the original submission."""
        return self.links[0]

    @property
    def head(self) -> ChainLink:
        """The newest link — the retained row."""
        return self.links[-1]

    @property
    def origin_icn(self) -> str:
        """Shortcut for ``self.origin.icn``."""
        return self.origin.icn

    @property
    def head_icn(self) -> str:
        """Shortcut for ``self.head.icn``."""
        return self.head.icn

    @property
    def txn_codes(self) -> tuple[str, ...]:
        """Oldest-to-newest Transaction Codes along the chain."""
        return tuple(link.txn_code for link in self.links)


def build_chains(df: pd.DataFrame) -> list[Chain]:
    """Build cross-reference chains from the transaction data.

    A chain starts at an original row (Xref is null) whose ICN was later
    superseded (appears as someone else's Xref).  Each successive link is
    the row whose Xref equals the previous link's ICN.

    Each :class:`ChainLink` carries its Transaction Code, and each
    :class:`Chain` records the origin row's Pharmacy NPI, so downstream
    reports don't need to rebuild auxiliary ICN->code / ICN->NPI maps.

    Parameters:
        df: Transaction DataFrame with ICN, Xref, Transaction Code, and
            Pharmacy NPI columns (all in :data:`REQUIRED_COLUMNS`).

    Returns:
        List of multi-link chains ordered from oldest to newest within
        each chain.  Single-link prescriptions are excluded.
    """
    all_xrefs: set[str] = set(df[BEACON_COL_XREF].dropna())

    # Pre-compute the two per-ICN lookups once so every link / chain can
    # be decorated in O(1) without touching the DataFrame in the hot loop.
    icn_to_code: dict[str, str] = dict(
        zip(df[BEACON_COL_ICN], df[BEACON_COL_TXN_CODE]),
    )
    icn_to_npi: dict[str, str] = dict(
        zip(df[BEACON_COL_ICN], df[BEACON_COL_PHARMACY_NPI]),
    )

    def _lookup(mapping: dict[str, str], icn: str) -> str:
        # ``or ""`` collapses pd.NA / None into the empty-string sentinel
        # the downstream reports already treat as "missing".
        value: str | None = mapping.get(icn)
        return value if isinstance(value, str) else ""

    def _link(index: int, icn: str, xref: str | None) -> ChainLink:
        return ChainLink(
            index=index,
            icn=icn,
            xref=xref,
            txn_code=_lookup(icn_to_code, icn),
        )

    # Chain Links: maps a superseded ICN to the row that replaced it.
    # Only rows WITH an Xref value participate here.  A row has an Xref
    # when the prescription was resubmitted through the switch — the Xref
    # column records the ICN of the previous submission it replaced.
    # Rows WITHOUT an Xref were never a replacement for anything; they are
    # either standalone prescriptions or the first submission in a chain.
    has_xref: pd.DataFrame = df.dropna(subset=[BEACON_COL_XREF])
    xref_rows: dict[str, ChainLink] = {
        row.Xref: _link(row.Index, row.ICN, row.Xref)
        for row in has_xref.itertuples()
    }

    # Chain origins: the first submission of a prescription that was
    # subsequently resubmitted.  These rows have no Xref (nothing before
    # them), but their ICN appears in another row's Xref (something
    # replaced them).  Each origin is the starting point of a chain.
    is_original: pd.Series = df[BEACON_COL_XREF].isna()
    was_superseded: pd.Series = df[BEACON_COL_ICN].isin(all_xrefs)
    origins: pd.DataFrame = df[is_original & was_superseded]

    chains: list[Chain] = []
    for row in origins.itertuples():
        links: list[ChainLink] = [_link(row.Index, row.ICN, None)]
        visited: set[str] = {row.ICN}
        current_icn: str = row.ICN

        # Follow the forward lookup until no row references current_icn.
        # ``visited`` breaks cycles introduced by corrupted data so the walk
        # cannot run forever; without it, A->B->A would loop indefinitely.
        while current_icn in xref_rows:
            next_link: ChainLink = xref_rows[current_icn]
            if next_link.icn in visited:
                log.warning(
                    "Cycle detected in xref chain starting at ICN %s; "
                    "stopping walk at %s.",
                    row.ICN, next_link.icn,
                )
                break
            links.append(next_link)
            visited.add(next_link.icn)
            current_icn = next_link.icn

        if len(links) > 1:
            chains.append(
                Chain(
                    links=tuple(links),
                    origin_npi=_lookup(icn_to_npi, row.ICN),
                ),
            )

    return chains


def get_retained_df(df: pd.DataFrame) -> pd.DataFrame:
    """Return the subset of rows to keep after deduplication.

    A row is retained if its ICN never appears as any other row's Xref,
    meaning it was never superseded by a later transaction.  The set of
    superseded ICNs is computed internally so callers don't have to
    duplicate the bookkeeping.

    Parameters:
        df: Transaction DataFrame with ICN and Xref columns.

    Returns:
        Filtered DataFrame containing only the retained rows.
    """
    all_xrefs: set[str] = set(df[BEACON_COL_XREF].dropna())
    mask: pd.Series = ~df[BEACON_COL_ICN].isin(all_xrefs)
    return df[mask].copy()
