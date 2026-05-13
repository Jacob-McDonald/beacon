"""Xref-chain listing and retained-ICN summary writers."""

from __future__ import annotations

from pathlib import Path

from beacon.processing import Chain, ChainLink


def tally_chain_lengths(chains: list[Chain]) -> dict[int, int]:
    """Count how many chains exist at each depth (2-link, 3-link, etc.).

    Used by both this module and :mod:`beacon.reports.analytics`.
    """
    counts: dict[int, int] = {}
    for chain in chains:
        counts[chain.depth] = counts.get(chain.depth, 0) + 1
    return counts


def write_chain_report(
    chains: list[Chain],
    total_rows: int,
    retained_count: int,
    path: Path,
) -> None:
    """Write a human-readable chain report to a text file.

    Parameters:
        chains: List of chains from ``build_chains``.
        total_rows: Total data rows in the original spreadsheet.
        retained_count: Number of rows kept after deduplication.
        path: Output file path.
    """
    lines: list[str] = []
    lines.append("")
    lines.append("")
    lines.append("           ICN              ICN Xref")
    lines.append("")

    # Each chain prints as a blank-line separated group.
    # Row numbers are 1-based to match spreadsheet rows.
    for chain in chains:
        lines.append("")
        for link in chain.links:
            row_display: int = link.index + 1
            xref_str: str = f"  {link.xref}" if link.xref is not None else ""
            lines.append(f"      {row_display:>4} {link.icn}{xref_str} ")
        lines.append("")

    length_counts: dict[int, int] = tally_chain_lengths(chains)

    discarded: int = total_rows - retained_count
    lines.append("")
    lines.append("=" * 60)
    lines.append("  Summary")
    lines.append("=" * 60)
    lines.append(f"  Total rows in spreadsheet:  {total_rows}")
    lines.append(f"  Rows retained (kept):       {retained_count}")
    lines.append(f"  Rows discarded (superseded): {discarded}")
    lines.append(f"  Number of chains:           {len(chains)}")
    lines.append("  Chain length distribution:")
    for length in sorted(length_counts):
        lines.append(f"    {length}-link chains: {length_counts[length]}")
    lines.append("=" * 60)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_retained_icns_report(chains: list[Chain], path: Path) -> None:
    """Write a report listing only the retained ICN from each chain.

    The retained ICN is the final link in each chain — the one whose
    ICN does not appear in any other row's Xref column.  Sorted by
    chain length descending so the most complex duplicates are at the
    top.

    Parameters:
        chains: List of chains from ``build_chains``.
        path: Output file path.
    """
    sorted_chains: list[Chain] = sorted(
        chains, key=lambda c: c.depth, reverse=True,
    )

    lines: list[str] = ["", "", ""]

    for chain in sorted_chains:
        head: ChainLink = chain.head
        row_display: int = head.index + 1

        if head.xref is not None:
            mid: str = f"  {head.xref}{row_display:>12}"
        else:
            mid = f"{row_display:>29}"

        lines.append(f"         {head.icn}{mid}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
