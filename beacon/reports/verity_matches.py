"""Verity_Matches diagnostic report.

Summarises the per-source pre/post-filter counts, the ``Eligible=YES``
duplicate audit, and the ``Verity_Matches`` YES/NO enrichment totals.
Consumed by pipeline Step 10.5.
"""

from __future__ import annotations

from pathlib import Path

from beacon.verity_matches import (
    DuplicateGroupDetail,
    EligibleDupReport,
    EligibleTripleDupReport,
    SourceSummary,
)


def _sources_section(
    source_summaries: list[SourceSummary],
    combined_rows: int,
) -> list[str]:
    """Header + per-file pre/post-filter counts."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  VERITY_MATCHES ENRICHMENT")
    lines.append("=" * 80)
    lines.append("")
    lines.append("  Filters each input file to Match NPI in the four pharmacy NPIs,")
    lines.append("  then appends a Verity_Matches YES/NO column to the enriched")
    lines.append("  Beacon frame based on (Pharmacy NPI, Rx Num, Fill Num) membership.")
    lines.append("")
    lines.append("  SOURCES")
    lines.append("  " + "-" * 40)

    # Pad filename column so per-file counts line up vertically.
    names: list[str] = [s.path.name for s in source_summaries]
    name_width: int = max((len(n) for n in names), default=20)
    header: str = (
        f"  {'File':<{name_width}s}  "
        f"{'Rows before':>11s}  {'Rows after':>11s}  {'Kept':>7s}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    total_before: int = 0
    total_after: int = 0
    for summary in source_summaries:
        total_before += summary.rows_before
        total_after += summary.rows_after
        pct: float = (
            summary.rows_after / summary.rows_before
            if summary.rows_before > 0
            else 0.0
        )
        lines.append(
            f"  {summary.path.name:<{name_width}s}  "
            f"{summary.rows_before:>11d}  {summary.rows_after:>11d}  "
            f"{pct:>6.2%}"
        )
    grand_pct: float = (total_after / total_before) if total_before > 0 else 0.0
    lines.append("  " + "-" * (len(header) - 2))
    lines.append(
        f"  {'TOTAL':<{name_width}s}  "
        f"{total_before:>11d}  {total_after:>11d}  "
        f"{grand_pct:>6.2%}"
    )
    lines.append("")
    if combined_rows != total_after:
        lines.append(
            f"  Note: combined filtered frame has {combined_rows} rows "
            f"(differs from the TOTAL above if deduplication or reset was applied)."
        )
        lines.append("")
    lines.append("")
    return lines


def _dupe_section(dupe: EligibleDupReport) -> list[str]:
    """Eligible=YES duplicate audit section keyed on ``(Rx, Fill)``."""
    lines: list[str] = []
    lines.append("  ELIGIBLE == YES DUPLICATE AUDIT  [key: (Rx, Fill)]")
    lines.append("  " + "-" * 40)
    lines.append("  Counts rows participating in duplicate (Rx Number, Disp Fill #)")
    lines.append("  pairs among Eligible=YES rows, IGNORING Match NPI.  Cross-pharmacy")
    lines.append("  Rx collisions show up here because Rx numbers are pharmacy-local.")
    lines.append("  For the join-key audit, see the next section.")
    lines.append("")
    lines.append(
        f"  Eligible=YES rows with parseable (Rx, Fill): {dupe.eligible_rows}"
    )
    lines.append(
        f"  Rows participating in duplicate groups:      {dupe.participant_count}"
    )
    if dupe.participant_count > 0:
        lines.append("")
        lines.append("  Sample colliding (Rx, Fill) pairs:")
        for rx, fill in dupe.sample:
            lines.append(f"    Rx {rx}  Fill {fill}")
        # The sample is capped at 10 unique groups; hitting the cap is the
        # only reliable signal that more groups exist beyond what's shown.
        if len(dupe.sample) >= 10:
            lines.append(
                f"    ... (showing first {len(dupe.sample)} groups)"
            )
    else:
        lines.append("  No duplicates among Eligible=YES rows.")
    lines.append("")
    lines.append("")
    return lines


def _triple_dupe_section(dupe: EligibleTripleDupReport) -> list[str]:
    """Eligible=YES audit keyed on the actual ``(Match NPI, Rx, Fill)`` join key."""
    lines: list[str] = []
    lines.append(
        "  ELIGIBLE == YES DUPLICATE AUDIT  [key: (Match NPI, Rx, Fill)]"
    )
    lines.append("  " + "-" * 40)
    lines.append("  Keyed on the same (NPI, Rx, Fill) triple the enrichment step uses.")
    lines.append("  A non-zero count here means two filtered rows would both match")
    lines.append("  the same Beacon row, which IS a data-quality issue worth fixing.")
    lines.append("")
    lines.append(
        f"  Eligible=YES rows with parseable (NPI, Rx, Fill): {dupe.eligible_rows}"
    )
    lines.append(
        f"  Rows participating in duplicate groups:           {dupe.participant_count}"
    )
    if dupe.participant_count > 0:
        lines.append("")
        lines.append("  Sample colliding (NPI, Rx, Fill) triples:")
        for npi, rx, fill in dupe.sample:
            lines.append(f"    NPI {npi}  Rx {rx}  Fill {fill}")
        if len(dupe.sample) >= 10:
            lines.append(
                f"    ... (showing first {len(dupe.sample)} groups)"
            )
    else:
        lines.append("  No (NPI, Rx, Fill) duplicates among Eligible=YES rows.")
    lines.append("")
    lines.append("")
    return lines


def _enrichment_section(enriched_yes: int, enriched_no: int) -> list[str]:
    """YES/NO tally of the appended Verity_Matches column."""
    total: int = enriched_yes + enriched_no
    yes_pct: float = (enriched_yes / total) if total > 0 else 0.0
    no_pct: float = (enriched_no / total) if total > 0 else 0.0
    lines: list[str] = []
    lines.append("  ENRICHMENT SUMMARY")
    lines.append("  " + "-" * 40)
    lines.append(f"  Beacon rows (enriched): {total}")
    lines.append(f"  Verity_Matches = YES:   {enriched_yes}  ({yes_pct:>7.2%})")
    lines.append(f"  Verity_Matches = NO:    {enriched_no}  ({no_pct:>7.2%})")
    lines.append("")
    lines.append("=" * 80)
    lines.append("")
    return lines


def write_verity_matches_report(
    source_summaries: list[SourceSummary],
    combined_rows: int,
    dupe_report: EligibleDupReport,
    triple_dupe_report: EligibleTripleDupReport,
    enriched_yes: int,
    enriched_no: int,
    path: Path,
) -> None:
    """Write the Verity_Matches diagnostic report.

    Sections: sources (per-file pre/post-filter counts + totals), the
    original ``(Rx, Fill)`` Eligible=YES audit, the ``(Match NPI, Rx, Fill)``
    join-key audit, and the enrichment totals (YES/NO percentages).

    Parameters:
        source_summaries: One entry per input file processed.
        combined_rows: Row count of the concatenated filtered frame.
        dupe_report: Result of
                     :func:`beacon.verity_matches.count_eligible_duplicates`.
        triple_dupe_report: Result of
            :func:`beacon.verity_matches.count_eligible_triple_duplicates`
            (keyed on the enrichment join key).
        enriched_yes: Beacon rows flagged ``YES`` in the new column.
        enriched_no: Beacon rows flagged ``NO`` in the new column.
        path: Output file path.
    """
    lines: list[str] = []
    lines += _sources_section(source_summaries, combined_rows)
    lines += _dupe_section(dupe_report)
    lines += _triple_dupe_section(triple_dupe_report)
    lines += _enrichment_section(enriched_yes, enriched_no)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-group (NPI, Rx, Fill) duplicate detail report.
# ---------------------------------------------------------------------------


# Width of the column-name column in each group's field dump.  Chosen to
# fit the longest entry in VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS with a
# small trailing gap.
_DUPES_FIELD_WIDTH: int = 24


def _format_group(index: int, group: DuplicateGroupDetail) -> list[str]:
    """Render one duplicate group as text lines, same/DIFF + diagnosis."""
    lines: list[str] = []
    banner: str = "=" * 80
    lines.append(banner)
    lines.append(
        f"  GROUP {index}: NPI={group.npi}  Rx={group.rx}  Fill={group.fill}  "
        f"({len(group.rows)} rows)"
    )
    lines.append(banner)

    # Each snapshot has the same column ordering, so we can zip them by
    # column index to determine same vs diff.
    n_rows: int = len(group.rows)
    n_cols: int = len(group.rows[0].values) if n_rows > 0 else 0
    for col_idx in range(n_cols):
        col_name: str = group.rows[0].values[col_idx][0]
        values: list[str] = [snap.values[col_idx][1] for snap in group.rows]
        all_same: bool = all(v == values[0] for v in values)
        if all_same:
            lines.append(
                f"  {col_name:<{_DUPES_FIELD_WIDTH}s}  [same]  {values[0]}"
            )
        else:
            lines.append(f"  {col_name:<{_DUPES_FIELD_WIDTH}s}  [DIFF]")
            for i, v in enumerate(values, start=1):
                lines.append(f"      row {i}: {v}")

    lines.append("")
    lines.append("  DIAGNOSIS:")
    lines.append(f"    {group.diagnosis}")
    lines.append("")
    lines.append("")
    return lines


def write_verity_matches_duplicates_report(
    details: tuple[DuplicateGroupDetail, ...],
    path: Path,
) -> None:
    """Write the per-group ``(NPI, Rx, Fill)`` duplicate detail report.

    One section per duplicate group, each containing a ``[same]`` /
    ``[DIFF]`` column dump followed by a rules-based cause diagnosis.
    The file is always written even when *details* is empty, so the
    pipeline can rely on a predictable output path.

    Parameters:
        details: Groups produced by
                 :func:`beacon.verity_matches.collect_duplicate_group_details`.
        path: Output file path.
    """
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  VERITY_MATCHES  (NPI, Rx, Fill) DUPLICATE DETAIL REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(
        "  One section per duplicate group among Eligible=YES rows, keyed on"
    )
    lines.append(
        "  (Match NPI, Rx Number, Disp Fill #) — the same triple used by the"
    )
    lines.append(
        "  Beacon enrichment step.  Each section lists every diagnostic"
    )
    lines.append(
        "  column as [same] when all rows agree or [DIFF] with per-row"
    )
    lines.append(
        "  values.  A short rules-based DIAGNOSIS line speculates on the"
    )
    lines.append(
        "  likely cause (see beacon.verity_matches.diagnose_group)."
    )
    lines.append("")

    if len(details) == 0:
        lines.append(
            "  No (NPI, Rx, Fill) duplicate groups among Eligible=YES rows."
        )
        lines.append("")
        lines.append("=" * 80)
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    lines.append(f"  Total duplicate groups: {len(details)}")
    lines.append("")
    lines.append("")
    for i, group in enumerate(details, start=1):
        lines += _format_group(i, group)
    lines.append("=" * 80)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
