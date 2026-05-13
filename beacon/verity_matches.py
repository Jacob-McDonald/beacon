"""Verity_Matches workbook: pharmacy filter, duplicate audit, Beacon YES/NO enrichment.

A *Verity_Matches* export is a 67-column ``.xlsx`` (sheet ``New Matches``) of
dispensing-match records produced by Verity.  Two shapes are supported:

1. A folder of monthly files named ``<Mon>_<YYYY>_Verity_Matches.xlsx``
   (e.g. ``Apr_2026_Verity_Matches.xlsx``).  All files in the folder
   matching :data:`beacon.constants.VERITY_MATCHES_FILE_GLOB` are loaded,
   filtered to the four pharmacy NPIs, then concatenated in calendar order.
2. A single through-range ``.xlsx`` (e.g.
   ``Verity_Matches_Oct_2025_thru_Apr_2026.xlsx``).  The file is loaded,
   filtered, and returned as-is.

Downstream, the filtered frame feeds:

- :func:`count_eligible_duplicates` — audits ``(Rx Number, Disp Fill #)``
  duplicates among ``Eligible == "YES"`` rows.
- :func:`verity_matches_triple_set` — builds the ``(Match NPI, Rx, Fill)``
  join key set.
- :func:`enrich_with_verity_matches` — adds a ``Verity_Matches`` YES/NO
  column to the enriched Beacon frame by membership in that set.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from beacon.constants import (
    BEACON_COL_FILL_NUM,
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_RX_NUM,
    BEACON_COL_VERITY_MATCHES,
    BEACON_PHARMACY_NPIS,
    VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS,
    VERITY_MATCHES_DUPLICATES_REPORT_FILE,
    VERITY_MATCHES_ELIGIBLE_COL,
    VERITY_MATCHES_FILE_GLOB,
    VERITY_MATCHES_FILL_COL,
    VERITY_MATCHES_FILTERED_BASENAME,
    VERITY_MATCHES_MATCH_NPI_COL,
    VERITY_MATCHES_REPORT_FILE,
    VERITY_MATCHES_RX_COL,
    VERITY_MATCHES_SHEET,
    _SOURCE_FILE_COL,
)
from beacon.keys import fill_key_series, npi_key_series, rx_key_series
from beacon.processing.writers import write_filtered_excel


# ---------------------------------------------------------------------------
# Result types (frozen dataclasses so callers can rely on stable attributes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSummary:
    """Per-source row counts before and after the pharmacy-NPI filter."""

    path: Path
    rows_before: int
    rows_after: int


@dataclass(frozen=True, slots=True)
class VerityMatchesLoad:
    """Combined output of :func:`load_verity_matches`.

    Attributes:
        frame: NPI-filtered Verity_Matches frame (all 67 original
               columns preserved).  When multiple monthly files feed in,
               they're concatenated in calendar order.
        summaries: Per-source before/after row counts, one entry per
                   input file (always at least one).
    """

    frame: pd.DataFrame
    summaries: tuple[SourceSummary, ...]


@dataclass(frozen=True, slots=True)
class EligibleDupReport:
    """Result of auditing ``(Rx, Fill)`` collisions among ``Eligible == YES``.

    Attributes:
        eligible_rows: Total rows with ``Eligible == YES`` and parseable
                       ``(Rx, Fill)`` keys.
        participant_count: Number of those rows participating in duplicate
                           ``(Rx, Fill)`` groups (``0`` when no duplicates).
        sample: Up to 10 representative ``(Rx, Fill)`` pairs that collide;
                useful for quick inspection without dumping the full set.
    """

    eligible_rows: int
    participant_count: int
    sample: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DuplicateRowSnapshot:
    """Frozen snapshot of one row in a ``(NPI, Rx, Fill)`` duplicate group.

    Only the columns listed in
    :data:`beacon.constants.VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS` are
    retained — the full 67-column source row is intentionally compressed
    so the report is focused and the dataclass stays cheap to build.

    Attributes:
        source_file: Originating monthly workbook name (sentinel value of
                     :data:`beacon.constants._SOURCE_FILE_COL`).
        match_id: Verity-generated unique match identifier.  Empty string
                  when the source row had no ``MatchId`` value.
        values: Immutable ``(column_name, str_value)`` pairs in the order
                defined by
                :data:`beacon.constants.VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS`.
    """

    source_file: str
    match_id: str
    values: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class DuplicateGroupDetail:
    """Frozen detail of one ``(NPI, Rx, Fill)`` duplicate group.

    Attributes:
        npi: Canonical 10-digit pharmacy NPI key.
        rx: 12-char zero-padded Rx key.
        fill: Integer fill number.
        rows: One snapshot per participating row (length >= 2).
        diagnosis: Short rules-based cause speculation produced by
                   :func:`diagnose_group`.
    """

    npi: str
    rx: str
    fill: int
    rows: tuple[DuplicateRowSnapshot, ...]
    diagnosis: str


@dataclass(frozen=True, slots=True)
class EligibleTripleDupReport:
    """Result of auditing ``(Match NPI, Rx, Fill)`` collisions among
    ``Eligible == YES`` rows — the actual Beacon→Verity join key.

    Unlike :class:`EligibleDupReport`, this audit keys on the pharmacy NPI
    as well.  A collision here is a true intra-pharmacy duplicate of the
    enrichment join key, so a non-zero count means two filtered rows would
    compete for the same Beacon match.

    Attributes:
        eligible_rows: Total rows with ``Eligible == YES`` and parseable
                       ``(NPI, Rx, Fill)`` keys.
        participant_count: Number of those rows participating in duplicate
                           ``(NPI, Rx, Fill)`` groups.
        sample: Up to 10 representative ``(NPI, Rx, Fill)`` triples.
    """

    eligible_rows: int
    participant_count: int
    sample: tuple[tuple[str, str, int], ...]


# ---------------------------------------------------------------------------
# Monthly filename parsing: sort files in calendar order before concatenation.
# ---------------------------------------------------------------------------


_MONTH_TO_INDEX: dict[str, int] = {
    m: i
    for i, m in enumerate(
        (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ),
        start=1,
    )
}
_MONTHLY_FILENAME_RE: re.Pattern[str] = re.compile(
    r"^(?P<month>[A-Za-z]{3})_(?P<year>\d{4})_Verity_Matches\.xlsx$",
)


def _calendar_sort_key(path: Path) -> tuple[int, int, str]:
    """Sort key for monthly filenames; unrecognised names sort last by name."""
    m: re.Match[str] | None = _MONTHLY_FILENAME_RE.match(path.name)
    if m is None:
        return (9999, 99, path.name)
    month_idx: int = _MONTH_TO_INDEX.get(m.group("month").capitalize(), 99)
    year: int = int(m.group("year"))
    return (year, month_idx, path.name)


# ---------------------------------------------------------------------------
# Load + filter: the two entry points a caller needs.
# ---------------------------------------------------------------------------


def _filter_one(path: Path) -> tuple[pd.DataFrame, SourceSummary]:
    """Read one Verity_Matches file, filter by pharmacy NPI, record counts."""
    try:
        df: pd.DataFrame = pd.read_excel(
            path,
            sheet_name=VERITY_MATCHES_SHEET,
            engine="openpyxl",
            dtype="string",
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to read Verity_Matches file: {path}") from exc
    df.columns = df.columns.str.strip()

    required: tuple[str, ...] = (
        VERITY_MATCHES_MATCH_NPI_COL,
        VERITY_MATCHES_ELIGIBLE_COL,
        VERITY_MATCHES_RX_COL,
        VERITY_MATCHES_FILL_COL,
    )
    missing: list[str] = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path.name}: missing required columns {missing}. "
            f"Found: {list(df.columns)}",
        )

    rows_before: int = len(df)
    # Tag every row with its originating file so downstream dupe-detail
    # reporting can tell whether a collision spans multiple monthly files.
    df[_SOURCE_FILE_COL] = path.name
    npi_norm: pd.Series = npi_key_series(df[VERITY_MATCHES_MATCH_NPI_COL])
    mask: pd.Series = npi_norm.isin(BEACON_PHARMACY_NPIS)
    filtered: pd.DataFrame = df.loc[mask].reset_index(drop=True)
    return filtered, SourceSummary(
        path=path,
        rows_before=rows_before,
        rows_after=len(filtered),
    )


def load_verity_matches(path: Path) -> VerityMatchesLoad:
    """Load and NPI-filter one or more Verity_Matches workbooks.

    Parameters:
        path: A single ``.xlsx`` file OR a directory containing monthly
              ``*_Verity_Matches.xlsx`` files.

    Returns:
        :class:`VerityMatchesLoad` whose ``frame`` contains every original
        column with rows restricted to the four pharmacy NPIs in
        :data:`beacon.constants.BEACON_PHARMACY_NPIS`.  Monthly files are
        concatenated in calendar order.  ``summaries`` holds one entry
        per input file with before/after row counts.

    Raises:
        FileNotFoundError: If *path* does not exist, or a directory contains
            no files matching :data:`beacon.constants.VERITY_MATCHES_FILE_GLOB`.
        ValueError: If any required column is absent from any source file.
    """
    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if path.is_file():
        sources: list[Path] = [path]
    else:
        sources = sorted(path.glob(VERITY_MATCHES_FILE_GLOB), key=_calendar_sort_key)
        if not sources:
            raise FileNotFoundError(
                f"No files matching {VERITY_MATCHES_FILE_GLOB!r} in {path}",
            )

    parts: list[pd.DataFrame] = []
    summaries: list[SourceSummary] = []
    for src in sources:
        filtered, summary = _filter_one(src)
        parts.append(filtered)
        summaries.append(summary)

    combined: pd.DataFrame = (
        pd.concat(parts, ignore_index=True)
        if len(parts) > 1
        else parts[0]
    )
    return VerityMatchesLoad(frame=combined, summaries=tuple(summaries))


# ---------------------------------------------------------------------------
# Duplicate audit: (Rx, Fill) collisions among Eligible == "YES".
# ---------------------------------------------------------------------------


def _is_eligible_yes(series: pd.Series) -> pd.Series:
    """Boolean mask of ``Eligible`` cells equal to ``YES`` (case/space insensitive)."""
    normalised: pd.Series = (
        series.astype("string").str.strip().str.upper()
    )
    return normalised == "YES"


def count_eligible_duplicates(df: pd.DataFrame) -> EligibleDupReport:
    """Audit ``(Rx, Fill)`` collisions among ``Eligible == YES`` rows.

    The normalised join key uses :func:`beacon.keys.rx_key` (12-digit
    zero-padded) and :func:`beacon.keys.fill_key` so the same comparison
    semantics apply here and in the enrichment step.  Rows whose Rx or
    Fill cannot be parsed are excluded from the audit (they cannot form
    a valid join key in any case).

    Parameters:
        df: Filtered Verity_Matches frame.

    Returns:
        :class:`EligibleDupReport` with totals plus up to 10 sample
        colliding ``(Rx, Fill)`` pairs.
    """
    eligible_mask: pd.Series = _is_eligible_yes(df[VERITY_MATCHES_ELIGIBLE_COL])
    sub: pd.DataFrame = df.loc[eligible_mask]
    rx_keys: pd.Series = rx_key_series(sub[VERITY_MATCHES_RX_COL])
    fill_keys: pd.Series = fill_key_series(sub[VERITY_MATCHES_FILL_COL])

    # Restrict to rows with well-formed keys — unparseable keys can't collide
    # deterministically and would pollute the duplicate count.
    valid_mask: pd.Series = rx_keys.ne("") & fill_keys.notna()
    keyed: pd.DataFrame = pd.DataFrame(
        {"rx": rx_keys[valid_mask], "fill": fill_keys[valid_mask]}
    )

    eligible_rows: int = int(valid_mask.sum())
    dup_mask: pd.Series = keyed.duplicated(subset=["rx", "fill"], keep=False)
    participant_count: int = int(dup_mask.sum())

    # Build up to 10 sample colliding pairs for the diagnostic report.
    sample_pairs: list[tuple[str, int]] = []
    if participant_count > 0:
        dup_rows: pd.DataFrame = keyed.loc[dup_mask]
        unique_pairs: pd.DataFrame = dup_rows.drop_duplicates(
            subset=["rx", "fill"], keep="first",
        ).head(10)
        for _, row in unique_pairs.iterrows():
            sample_pairs.append((str(row["rx"]), int(row["fill"])))

    return EligibleDupReport(
        eligible_rows=eligible_rows,
        participant_count=participant_count,
        sample=tuple(sample_pairs),
    )


def count_eligible_triple_duplicates(df: pd.DataFrame) -> EligibleTripleDupReport:
    """Audit ``(Match NPI, Rx, Fill)`` collisions among ``Eligible == YES``.

    This keys on the same ``(NPI, Rx, Fill)`` triple the enrichment step
    uses, so any collision here is a true intra-pharmacy duplicate of the
    join key.  Rows whose NPI/Rx/Fill cannot be parsed are excluded — they
    could never produce a deterministic join in the first place.

    Parameters:
        df: Filtered Verity_Matches frame.

    Returns:
        :class:`EligibleTripleDupReport` with totals plus up to 10 sample
        colliding ``(NPI, Rx, Fill)`` triples.
    """
    eligible_mask: pd.Series = _is_eligible_yes(df[VERITY_MATCHES_ELIGIBLE_COL])
    sub: pd.DataFrame = df.loc[eligible_mask]
    npi_keys: pd.Series = npi_key_series(sub[VERITY_MATCHES_MATCH_NPI_COL])
    rx_keys: pd.Series = rx_key_series(sub[VERITY_MATCHES_RX_COL])
    fill_keys: pd.Series = fill_key_series(sub[VERITY_MATCHES_FILL_COL])

    valid_mask: pd.Series = (
        npi_keys.ne("") & rx_keys.ne("") & fill_keys.notna()
    )
    keyed: pd.DataFrame = pd.DataFrame(
        {
            "npi": npi_keys[valid_mask],
            "rx": rx_keys[valid_mask],
            "fill": fill_keys[valid_mask],
        }
    )

    eligible_rows: int = int(valid_mask.sum())
    dup_mask: pd.Series = keyed.duplicated(
        subset=["npi", "rx", "fill"], keep=False,
    )
    participant_count: int = int(dup_mask.sum())

    sample_triples: list[tuple[str, str, int]] = []
    if participant_count > 0:
        dup_rows: pd.DataFrame = keyed.loc[dup_mask]
        unique_triples: pd.DataFrame = dup_rows.drop_duplicates(
            subset=["npi", "rx", "fill"], keep="first",
        ).head(10)
        for _, row in unique_triples.iterrows():
            sample_triples.append(
                (str(row["npi"]), str(row["rx"]), int(row["fill"])),
            )

    return EligibleTripleDupReport(
        eligible_rows=eligible_rows,
        participant_count=participant_count,
        sample=tuple(sample_triples),
    )


# ---------------------------------------------------------------------------
# Per-group duplicate detail: side-by-side column dump + rules-based cause.
# ---------------------------------------------------------------------------


def _render_cell(value: object) -> str:
    """Stable string representation for a cell used in the detail report.

    Pandas NA / NaN render as ``""`` so the ``[same]`` vs ``[DIFF]``
    comparison treats all missing values as equal.  Everything else goes
    through ``str()`` with surrounding whitespace stripped.
    """
    if pd.isna(value):
        return ""
    return str(value).strip()


def _parse_fill_date(value: str) -> pd.Timestamp | None:
    """Best-effort parse of a Verity ``Disp Fill Date`` string.

    Returns ``None`` when the value is empty or unparseable — the
    diagnosis rules treat that as "no date signal available" and fall
    through to the next rule.
    """
    if value == "":
        return None
    try:
        ts: pd.Timestamp = pd.to_datetime(value, errors="raise")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts


def _group_column_values(
    detail: DuplicateGroupDetail, column: str,
) -> list[str]:
    """Extract the per-row value of *column* for every snapshot in *detail*."""
    values: list[str] = []
    for snap in detail.rows:
        for name, raw in snap.values:
            if name == column:
                values.append(raw)
                break
    return values


def diagnose_group(detail: DuplicateGroupDetail) -> str:
    """Rules-based cause speculation for one ``(NPI, Rx, Fill)`` dup group.

    Rules are evaluated in priority order; the first that matches wins.
    Each rule inspects a small slice of :attr:`DuplicateGroupDetail.rows`
    and returns a one-sentence diagnosis intended for human review.

    Parameters:
        detail: The group to diagnose.  ``detail.diagnosis`` is ignored
                (this function produces it).

    Returns:
        A short human-readable cause string.
    """
    # Rule 1 — cross-file: rows appear in multiple monthly workbooks.
    source_files: list[str] = [s.source_file for s in detail.rows]
    if len(set(source_files)) > 1:
        unique_sorted: list[str] = sorted(set(source_files))
        return (
            f"Rows appear in different monthly files ({', '.join(unique_sorted)}) "
            f"— investigate download overlap."
        )

    # Rule 2 — identical MatchId across every row: re-ingest of one record.
    match_ids: list[str] = [s.match_id for s in detail.rows if s.match_id != ""]
    if len(match_ids) == len(detail.rows) and len(set(match_ids)) == 1:
        return "Identical MatchId across rows — duplicate ingest of one Verity record."

    # Rule 3 — distinct Match Type values (e.g. REFILL vs DISPENSE).
    match_types: list[str] = [v for v in _group_column_values(detail, "Match Type") if v != ""]
    if len(set(match_types)) > 1:
        variants: str = " vs ".join(sorted(set(match_types)))
        return (
            f"Verity matcher double-fired: Match Type differs ({variants}); "
            f"likely matcher over-trigger."
        )

    # Rules 4 / 5 — Disp Fill Date deltas signal distinct physical dispenses
    # vs consecutive-day double-matches.  Needs at least two parseable dates.
    fill_dates_raw: list[str] = _group_column_values(detail, "Disp Fill Date")
    parsed: list[pd.Timestamp] = [
        d for d in (_parse_fill_date(v) for v in fill_dates_raw) if d is not None
    ]
    if len(parsed) >= 2:
        span_days: float = abs((max(parsed) - min(parsed)).total_seconds()) / 86400.0
        if span_days > 7.0:
            return (
                "Distinct dispenses on different dates sharing Fill #; "
                "pharmacy-side Fill # not incremented "
                f"(Disp Fill Date spans {span_days:.0f} days)."
            )
        if span_days >= 1.0:
            return (
                "Consecutive-day duplicate; possible refill/dispense "
                f"double-match (Disp Fill Date differs by {span_days:.0f} day(s))."
            )

    # Rule 6 — financial discrepancy: different Total Paid values.
    paid_values: list[str] = [v for v in _group_column_values(detail, "Total Paid") if v != ""]
    if len(set(paid_values)) > 1:
        return "Financial discrepancy: different Total Paid between rows."

    # Rule 7 — fallback.
    return "Unknown pattern — manual review required."


def collect_duplicate_group_details(
    df: pd.DataFrame,
) -> tuple[DuplicateGroupDetail, ...]:
    """Build a :class:`DuplicateGroupDetail` for every ``(NPI, Rx, Fill)``
    collision among ``Eligible == YES`` rows with parseable keys.

    The slicing + key-normalisation matches
    :func:`count_eligible_triple_duplicates` so the two audits report on
    the same set of rows.  For each duplicate group, the diagnostic
    columns listed in
    :data:`beacon.constants.VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS` are
    captured into :class:`DuplicateRowSnapshot` objects, and a cause
    diagnosis is attached via :func:`diagnose_group`.

    Parameters:
        df: Filtered Verity_Matches frame (must carry the
            :data:`beacon.constants._SOURCE_FILE_COL` sentinel column
            added by :func:`_filter_one`).

    Returns:
        Tuple of details, sorted by ``(npi, rx, fill)``.  Empty when no
        duplicate groups exist.
    """
    eligible_mask: pd.Series = _is_eligible_yes(df[VERITY_MATCHES_ELIGIBLE_COL])
    sub: pd.DataFrame = df.loc[eligible_mask].copy()
    sub["_npi_key"] = npi_key_series(sub[VERITY_MATCHES_MATCH_NPI_COL])
    sub["_rx_key"] = rx_key_series(sub[VERITY_MATCHES_RX_COL])
    sub["_fill_key"] = fill_key_series(sub[VERITY_MATCHES_FILL_COL])

    valid_mask: pd.Series = (
        sub["_npi_key"].ne("")
        & sub["_rx_key"].ne("")
        & sub["_fill_key"].notna()
    )
    keyed: pd.DataFrame = sub.loc[valid_mask]
    dup_mask: pd.Series = keyed.duplicated(
        subset=["_npi_key", "_rx_key", "_fill_key"], keep=False,
    )
    dupes: pd.DataFrame = keyed.loc[dup_mask]
    if len(dupes) == 0:
        return ()

    details: list[DuplicateGroupDetail] = []
    # ``sort=True`` (default) keeps groups in deterministic (npi, rx, fill)
    # order so report output is reproducible across runs.
    for (npi, rx, fill), group in dupes.groupby(
        ["_npi_key", "_rx_key", "_fill_key"],
    ):
        snapshots: list[DuplicateRowSnapshot] = []
        for _, row in group.iterrows():
            values: list[tuple[str, str]] = []
            for col in VERITY_MATCHES_DUPE_DIAGNOSTIC_COLS:
                raw: object = row[col] if col in group.columns else ""
                values.append((col, _render_cell(raw)))
            source_file: str = (
                _render_cell(row[_SOURCE_FILE_COL])
                if _SOURCE_FILE_COL in group.columns
                else ""
            )
            match_id: str = (
                _render_cell(row["MatchId"]) if "MatchId" in group.columns else ""
            )
            snapshots.append(
                DuplicateRowSnapshot(
                    source_file=source_file,
                    match_id=match_id,
                    values=tuple(values),
                ),
            )
        provisional: DuplicateGroupDetail = DuplicateGroupDetail(
            npi=str(npi),
            rx=str(rx),
            fill=int(fill),
            rows=tuple(snapshots),
            diagnosis="",
        )
        diagnosis: str = diagnose_group(provisional)
        details.append(
            DuplicateGroupDetail(
                npi=provisional.npi,
                rx=provisional.rx,
                fill=provisional.fill,
                rows=provisional.rows,
                diagnosis=diagnosis,
            ),
        )
    return tuple(details)


# ---------------------------------------------------------------------------
# Join-key set + enrichment: add a YES/NO Verity_Matches column to Beacon.
# ---------------------------------------------------------------------------


def verity_matches_triple_set(df: pd.DataFrame) -> set[tuple[str, str, int]]:
    """Build the ``(Match NPI, Rx Number, Disp Fill #)`` key set.

    Rows with any missing or unparseable key component are skipped — they
    cannot contribute a deterministic join key.
    """
    npi_series: pd.Series = npi_key_series(df[VERITY_MATCHES_MATCH_NPI_COL])
    rx_series: pd.Series = rx_key_series(df[VERITY_MATCHES_RX_COL])
    fill_series: pd.Series = fill_key_series(df[VERITY_MATCHES_FILL_COL])

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


def enrich_with_verity_matches(
    enriched: pd.DataFrame,
    verity_matches_df: pd.DataFrame,
    *,
    column_name: str = BEACON_COL_VERITY_MATCHES,
) -> pd.DataFrame:
    """Append a ``YES``/``NO`` column indicating Verity_Matches membership.

    A Beacon row is ``YES`` when its ``(Pharmacy NPI, Rx Num, Fill Num)``
    triple appears in *verity_matches_df*; otherwise ``NO``.  Rows whose
    Beacon-side keys are missing or unparseable resolve to ``NO`` (they
    cannot form a valid join key).

    Parameters:
        enriched: Beacon frame after MTF + transaction-description
                  enrichment; must include ``Pharmacy NPI``, ``Rx Num``,
                  ``Fill Num``.
        verity_matches_df: Filtered Verity_Matches frame
                           (see :func:`load_verity_matches`).
        column_name: Name of the new column.  Defaults to
                     :data:`beacon.constants.BEACON_COL_VERITY_MATCHES`.

    Returns:
        A copy of *enriched* with the new column appended.
    """
    triples: set[tuple[str, str, int]] = verity_matches_triple_set(verity_matches_df)

    beacon_npi: pd.Series = npi_key_series(enriched[BEACON_COL_PHARMACY_NPI])
    beacon_rx: pd.Series = rx_key_series(enriched[BEACON_COL_RX_NUM])
    beacon_fill: pd.Series = fill_key_series(enriched[BEACON_COL_FILL_NUM])

    valid: pd.Series = (
        beacon_npi.ne("") & beacon_rx.ne("") & beacon_fill.notna()
    )
    hit: pd.Series = pd.Series(False, index=enriched.index)
    if triples and bool(valid.any()):
        # Vectorised set-membership via MultiIndex.isin over the valid rows;
        # invalid rows stay False by construction and resolve to "NO".
        verity_idx: pd.MultiIndex = pd.MultiIndex.from_tuples(
            triples, names=["npi", "rx", "fill"],
        )
        beacon_idx: pd.MultiIndex = pd.MultiIndex.from_arrays(
            [
                beacon_npi[valid].astype(str).to_numpy(),
                beacon_rx[valid].astype(str).to_numpy(),
                beacon_fill[valid].astype("int64").to_numpy(),
            ],
            names=["npi", "rx", "fill"],
        )
        hit.loc[valid] = beacon_idx.isin(verity_idx)

    out: pd.DataFrame = enriched.copy()
    out[column_name] = np.where(hit.to_numpy(), "YES", "NO")
    return out


def write_filtered_verity_matches(df: pd.DataFrame, path: Path) -> None:
    """Write the pharmacy-filtered combined Verity_Matches frame to *path*.

    Original Verity columns are preserved so the filtered artifact is a
    drop-in replacement for the source file(s), reduced to the four
    pharmacy NPIs.  Any underscore-prefixed sentinel columns added by the
    pipeline (e.g. :data:`beacon.constants._SOURCE_FILE_COL`) are stripped
    before writing so the exported workbook stays clean for consumers.
    """
    public_cols: list[str] = [c for c in df.columns if not str(c).startswith("_")]
    write_filtered_excel(df.loc[:, public_cols], path, sheet_name="Verity_Matches")


# ---------------------------------------------------------------------------
# End-to-end orchestration for the pipeline's Verity_Matches step.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerityMatchesStepResult:
    """Everything the pipeline needs from the Verity_Matches step.

    Attributes:
        enriched: Beacon frame with the ``Verity_Matches`` YES/NO
                  column appended.
        summaries: Per-source pre/post-filter counts.
        filtered_path: Location of the pharmacy-filtered combined
                       Verity_Matches workbook that was written.
        dupe_report: ``(Rx, Fill)`` audit among ``Eligible == YES`` rows.
        triple_dupe_report: ``(Match NPI, Rx, Fill)`` audit among
                            ``Eligible == YES`` rows — matches the actual
                            enrichment join key.
        duplicate_details: One :class:`DuplicateGroupDetail` per
                           ``(NPI, Rx, Fill)`` collision, with rendered
                           row snapshots and a rules-based diagnosis.
        yes_count: Number of Beacon rows flagged ``YES``.
        no_count: Number of Beacon rows flagged ``NO``.
        report_path: Location of the Verity_Matches summary report.
        duplicates_report_path: Location of the per-group duplicate
                                detail report (always written).
    """

    enriched: pd.DataFrame
    summaries: tuple[SourceSummary, ...]
    filtered_path: Path
    dupe_report: EligibleDupReport
    triple_dupe_report: EligibleTripleDupReport
    duplicate_details: tuple[DuplicateGroupDetail, ...]
    yes_count: int
    no_count: int
    report_path: Path
    duplicates_report_path: Path


def _derive_filtered_path(verity_matches_path: Path) -> Path:
    """Choose where to write the pharmacy-filtered combined Verity_Matches.

    For a directory input, sit the filtered workbook alongside the monthly
    sources.  For a single through-file input, append ``_Filtered`` to the
    stem so the output doesn't clobber the source.
    """
    if verity_matches_path.is_dir():
        return verity_matches_path / VERITY_MATCHES_FILTERED_BASENAME
    return verity_matches_path.with_name(
        f"{verity_matches_path.stem}_Filtered.xlsx",
    )


def process_verity_matches(
    enriched: pd.DataFrame,
    verity_matches_path: Path,
    reports_dir: Path,
) -> VerityMatchesStepResult:
    """Run the full Verity_Matches step: load, filter, audit, enrich, report.

    Keeps every Verity_Matches-specific choice (output paths, dupe audit,
    report layout) inside this module so the pipeline orchestrator can
    treat the step as a single unit.  Logging stays with the caller.

    Parameters:
        enriched: Beacon frame after MTF + transaction-description
                  enrichment (must include ``Pharmacy NPI``, ``Rx Num``,
                  ``Fill Num``).
        verity_matches_path: Single ``.xlsx`` OR directory of monthly
                             ``*_Verity_Matches.xlsx`` files.
        reports_dir: Destination directory for the diagnostic report.

    Returns:
        :class:`VerityMatchesStepResult` describing every artifact and
        counter the caller needs to log / propagate downstream.
    """
    # Deferred import: ``beacon.reports.verity_matches`` imports
    # ``EligibleDupReport`` / ``SourceSummary`` from this module, so a
    # top-level import here would form a cycle during package load.
    from beacon.reports import (
        write_verity_matches_duplicates_report,
        write_verity_matches_report,
    )

    load: VerityMatchesLoad = load_verity_matches(verity_matches_path)

    # Collect per-group dupe details BEFORE writing the filtered xlsx,
    # because ``write_filtered_verity_matches`` strips the sentinel
    # ``_Source_File`` column that the collector needs.  Running the
    # collector against ``load.frame`` (which still carries the sentinel)
    # keeps the two concerns independent.
    duplicate_details: tuple[DuplicateGroupDetail, ...] = (
        collect_duplicate_group_details(load.frame)
    )

    filtered_path: Path = _derive_filtered_path(verity_matches_path)
    write_filtered_verity_matches(load.frame, filtered_path)

    dupe_report: EligibleDupReport = count_eligible_duplicates(load.frame)
    triple_dupe_report: EligibleTripleDupReport = count_eligible_triple_duplicates(
        load.frame,
    )

    enriched_out: pd.DataFrame = enrich_with_verity_matches(enriched, load.frame)
    yes_count: int = int((enriched_out[BEACON_COL_VERITY_MATCHES] == "YES").sum())
    no_count: int = int((enriched_out[BEACON_COL_VERITY_MATCHES] == "NO").sum())

    report_path: Path = reports_dir / VERITY_MATCHES_REPORT_FILE
    write_verity_matches_report(
        list(load.summaries),
        len(load.frame),
        dupe_report,
        triple_dupe_report,
        yes_count,
        no_count,
        report_path,
    )

    duplicates_report_path: Path = reports_dir / VERITY_MATCHES_DUPLICATES_REPORT_FILE
    write_verity_matches_duplicates_report(duplicate_details, duplicates_report_path)

    return VerityMatchesStepResult(
        enriched=enriched_out,
        summaries=load.summaries,
        filtered_path=filtered_path,
        dupe_report=dupe_report,
        triple_dupe_report=triple_dupe_report,
        duplicate_details=duplicate_details,
        yes_count=yes_count,
        no_count=no_count,
        report_path=report_path,
        duplicates_report_path=duplicates_report_path,
    )
