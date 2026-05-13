"""Rx/Fill duplicate reports: classify same-pharmacy collisions.

A retained row is the head of a multi-link chain (the most recent
submission Beacon kept).  When two retained rows for the **same
pharmacy** share the same ``(Rx Num, Fill Num)`` they are flagged as
a duplicate group and classified by the full oldest-to-newest
transaction-code sequence of their respective chains.

Rx numbers are issued per pharmacy, so the same ``(Rx, Fill)`` under
two different NPIs is not a duplicate — the key is therefore
``(Pharmacy NPI, Rx Num, Fill Num)``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_COL_FILL_NUM,
    BEACON_COL_ICN,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_RX_NUM,
    BEACON_COL_TXN_CODE,
    TRANSACTION_CODE_DESCRIPTIONS,
)
from beacon.processing import Chain
from beacon.reports._common import location_name


@dataclass(frozen=True, slots=True)
class _DupRow:
    """One retained row of a duplicate group with its full chain codes."""

    head_icn: str
    npi: str
    chain_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _DupGroup:
    """All retained rows sharing the same (Pharmacy NPI, Rx Num, Fill Num).

    Because the key includes NPI, every row in *rows* belongs to the
    same pharmacy — ``npi`` is stored once on the group rather than
    being re-derived from a row.
    """

    npi: str
    rx: str
    fill: str
    rows: tuple[_DupRow, ...]


# A group's pattern is the ordered tuple of each row's chain-code sequence.
_Pattern = tuple[tuple[str, ...], ...]


# Display labels for the *terminal* transaction code of a chain — the
# single code that determines the chain's final business state.  Codes
# not listed here fall back to the canonical short description in
# TRANSACTION_CODE_DESCRIPTIONS.
_TERMINAL_STATE_LABELS: dict[str, str] = {
    "001": "Active Original",
    "002": "Active Adjustment",
    "003": "Reversed",
    "004": "Informational",
    "011": "Active COB Original",
    "012": "Active COB Adjustment",
    "013": "Reversed COB",
    "021": "Active Unenrolled Original",
    "022": "Active Unenrolled Adjustment",
    "023": "Reversed Unenrolled",
    "092": "MFP Adjustment",
    "099": "No MFP Claims",
}


def _head_to_chain_map(chains: list[Chain]) -> dict[str, Chain]:
    """Map each multi-link chain's head ICN to its full chain."""
    return {chain.head_icn: chain for chain in chains}


def _icn_to_code_map(full_df: pd.DataFrame) -> dict[str, str]:
    """Fallback ICN->Transaction Code map for non-chain retained rows.

    Multi-link chains already carry their codes via
    :attr:`beacon.processing.Chain.txn_codes`, so this lookup only serves
    the single-link fallback path in :func:`_chain_codes_for_head` (a
    retained row whose ICN never headed an Xref chain).
    """
    icns: pd.Series = full_df[BEACON_COL_ICN].astype(str)
    codes: pd.Series = full_df[BEACON_COL_TXN_CODE].astype(str)
    return dict(zip(icns, codes))


def _chain_codes_for_head(
    head_icn: str,
    head_to_chain: dict[str, Chain],
    icn_to_code: dict[str, str],
) -> tuple[str, ...]:
    """Return the oldest-to-newest transaction codes for the chain of *head_icn*.

    A retained row whose ICN heads a multi-link chain returns the full
    sequence (from the chain's precomputed ``txn_codes``); a retained
    row with no prior submissions returns a single-code tuple derived
    from its own Transaction Code via the fallback *icn_to_code* map.
    """
    chain: Chain | None = head_to_chain.get(head_icn)
    if chain is None:
        code: str = icn_to_code.get(head_icn, "")
        return (code,) if code else ()
    return chain.txn_codes


def _build_duplicate_groups(
    enriched: pd.DataFrame,
    chains: list[Chain],
    full_df: pd.DataFrame,
) -> list[_DupGroup]:
    """Return every (NPI, Rx Num, Fill Num) group with more than one retained row.

    Rx numbers are issued per pharmacy, so two retained rows with the
    same Rx / Fill under different NPIs are *not* duplicates.  Grouping
    by NPI alongside Rx and Fill restricts collisions to a single MTF
    sheet at a time, which is the only setting in which a duplicate is
    operationally meaningful.

    Rows within each group are ordered by head ICN ascending so the
    caller can rely on a stable "submission-order" presentation.
    """
    # Rows with missing Rx/Fill cannot form duplicates we can reason about.
    needed: pd.DataFrame = enriched.dropna(
        subset=[BEACON_COL_RX_NUM, BEACON_COL_FILL_NUM]
    ).copy()
    needed[BEACON_COL_RX_NUM] = needed[BEACON_COL_RX_NUM].astype(str).str.strip()
    needed[BEACON_COL_FILL_NUM] = needed[BEACON_COL_FILL_NUM].astype(str).str.strip()
    needed[BEACON_COL_ICN] = needed[BEACON_COL_ICN].astype(str).str.strip()
    needed[BEACON_COL_PHARMACY_NPI] = (
        needed[BEACON_COL_PHARMACY_NPI].astype(str).str.strip()
    )

    head_to_chain: dict[str, Chain] = _head_to_chain_map(chains)
    icn_to_code: dict[str, str] = _icn_to_code_map(full_df)

    groups: list[_DupGroup] = []
    for (npi, rx, fill), raw in needed.groupby(
        [BEACON_COL_PHARMACY_NPI, BEACON_COL_RX_NUM, BEACON_COL_FILL_NUM],
        sort=False,
    ):
        if len(raw) <= 1:
            continue
        ordered: pd.DataFrame = raw.sort_values(BEACON_COL_ICN, kind="stable")
        rows: tuple[_DupRow, ...] = tuple(
            _DupRow(
                head_icn=str(r[BEACON_COL_ICN]),
                npi=str(r[BEACON_COL_PHARMACY_NPI]),
                chain_codes=_chain_codes_for_head(
                    str(r[BEACON_COL_ICN]), head_to_chain, icn_to_code,
                ),
            )
            for _, r in ordered.iterrows()
        )
        groups.append(
            _DupGroup(npi=str(npi), rx=str(rx), fill=str(fill), rows=rows),
        )
    return groups


def _format_chain(codes: tuple[str, ...]) -> str:
    """Render one chain's codes as e.g. ``001 -> 003`` or ``(empty)``."""
    return " -> ".join(codes) if codes else "(empty)"


def _group_pattern(group: _DupGroup) -> _Pattern:
    """Canonical pattern key for a group: chain-code sequences sorted.

    The order of rows within a duplicate group is not meaningful for
    classification (two chains for the same Rx/Fill have no inherent
    sequence); sorting produces a stable key so e.g.
    ``[001 -> 003] | [001]`` and ``[001] | [001 -> 003]`` collapse to
    the same pattern.  Arrow order *within* each chain is preserved
    because it is meaningful (oldest -> newest).
    """
    return tuple(sorted(row.chain_codes for row in group.rows))


def _format_pattern(pattern: _Pattern) -> str:
    """Render a pattern as ``[001] | [001 -> 003]`` for display."""
    return " | ".join(f"[{_format_chain(seq)}]" for seq in pattern)


def _terminal_label(code: str) -> str:
    """Short business-state label for a chain's terminal transaction code."""
    if code in _TERMINAL_STATE_LABELS:
        return _TERMINAL_STATE_LABELS[code]
    fallback: str | None = TRANSACTION_CODE_DESCRIPTIONS.get(code)
    return fallback if fallback is not None else code


def _describe_pattern(pattern: _Pattern) -> str:
    """Build a short insight line from the terminal code of each chain.

    Each chain is reduced to the business-state label of its *final* code,
    then labels are aggregated into a count-prefixed multiset — e.g.
    ``2 Reversed + 1 Active Original``.
    """
    terminals: list[str] = [chain[-1] for chain in pattern if chain]
    if not terminals:
        return "(no terminal codes)"
    counts: Counter[str] = Counter(terminals)
    ranked: list[tuple[str, int]] = sorted(
        counts.items(), key=lambda kv: (-kv[1], _terminal_label(kv[0])),
    )
    return " + ".join(f"{count} {_terminal_label(code)}" for code, count in ranked)


def _write_duplicate_patterns(groups: list[_DupGroup], path: Path) -> None:
    """Write the summary report: each distinct pattern with its group count."""
    pattern_counts: Counter[_Pattern] = Counter()
    for group in groups:
        pattern_counts[_group_pattern(group)] += 1

    by_size: dict[int, list[tuple[_Pattern, int]]] = defaultdict(list)
    for pattern, count in pattern_counts.items():
        by_size[len(pattern)].append((pattern, count))

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  RX/FILL DUPLICATE PATTERNS (within a single pharmacy)")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"  Total duplicate groups: {len(groups)}")
    lines.append(
        "  Duplicates are keyed on (Pharmacy NPI, Rx Num, Fill Num); same Rx/Fill"
    )
    lines.append("  under different NPIs is not a duplicate.")
    lines.append("  Pattern = the multiset of per-row chain code sequences")
    lines.append("  (oldest -> newest within each chain; row order is not significant).")
    lines.append("  Insight = business state of each chain based on its terminal code.")
    lines.append("")

    for size in sorted(by_size):
        size_total: int = sum(n for _, n in by_size[size])
        lines.append(f"  {size}-row duplicates: {size_total}")
        lines.append("  " + "-" * 40)
        ranked: list[tuple[_Pattern, int]] = sorted(
            by_size[size], key=lambda kv: (-kv[1], kv[0]),
        )
        pattern_strs: list[str] = [_format_pattern(p) for p, _ in ranked]
        pattern_width: int = max((len(s) for s in pattern_strs), default=0)

        for (pattern, count), pattern_str in zip(ranked, pattern_strs):
            insight: str = _describe_pattern(pattern)
            lines.append(
                f"    [{count:>3}]  {pattern_str:<{pattern_width}s}    {insight}"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_duplicate_groups(groups: list[_DupGroup], path: Path) -> None:
    """Write the detail report: every duplicate group listed under its pattern."""
    by_pattern: dict[_Pattern, list[_DupGroup]] = defaultdict(list)
    for group in groups:
        by_pattern[_group_pattern(group)].append(group)

    sorted_patterns: list[_Pattern] = sorted(
        by_pattern,
        key=lambda p: (len(p), -len(by_pattern[p]), p),
    )

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  RX/FILL DUPLICATE GROUPS (within a single pharmacy)")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"  Total duplicate groups: {len(groups)}")
    lines.append(
        "  Duplicates are keyed on (Pharmacy NPI, Rx Num, Fill Num); same Rx/Fill"
    )
    lines.append("  under different NPIs is not a duplicate.")
    lines.append("  Groups are ordered by pattern, then by Location, Rx Num, Fill Num.")
    lines.append("  Rows within each group are listed by head ICN ascending.")
    lines.append("  Each row shows its retained head ICN and the full chain's codes.")
    lines.append("")

    for pattern in sorted_patterns:
        group_list: list[_DupGroup] = sorted(
            by_pattern[pattern], key=lambda g: (g.npi, g.rx, g.fill),
        )
        lines.append("")
        lines.append("  " + "=" * 76)
        lines.append(
            f"  Pattern ({len(group_list)} group(s)):  {_format_pattern(pattern)}"
        )
        lines.append("  " + "=" * 76)
        for group in group_list:
            npi_display: str = location_name(group.npi)
            lines.append(
                f"    Rx {group.rx}  Fill {group.fill}  Location {npi_display}"
            )
            for row in group.rows:
                lines.append(
                    f"      head={row.head_icn}  "
                    f"chain=[{_format_chain(row.chain_codes)}]"
                )
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_duplicate_reports(
    enriched: pd.DataFrame,
    chains: list[Chain],
    full_df: pd.DataFrame,
    patterns_path: Path,
    groups_path: Path,
) -> None:
    """Write both Rx/Fill duplicate reports.

    A duplicate is any ``(Pharmacy NPI, Rx Num, Fill Num)`` that appears
    on more than one retained row.  Including NPI in the key restricts
    collisions to a single pharmacy — Rx numbers are issued per-pharmacy,
    so a shared ``(Rx, Fill)`` across two NPIs is not a real duplicate.

    Each retained row represents the head of one xref chain in the
    full-load workbook, so the unit of classification is the full
    oldest-to-newest Transaction Code sequence of that chain.  Rows
    within a group are ordered by the retained head's ICN ascending.

    Parameters:
        enriched: Retained rows after MTF enrichment (must include
                  ICN, Pharmacy NPI, Rx Num, Fill Num).
        chains: Multi-link chains from ``build_chains``; single-link
                chains are inferred from *full_df*.
        full_df: The unfiltered transactions DataFrame used to look up
                 each ICN's Transaction Code.
        patterns_path: Output path for the pattern-frequency summary.
        groups_path: Output path for the per-group detail listing.
    """
    groups: list[_DupGroup] = _build_duplicate_groups(enriched, chains, full_df)
    _write_duplicate_patterns(groups, patterns_path)
    _write_duplicate_groups(groups, groups_path)
