"""Verity claims overlap report.

Cross-references the enriched Beacon frame against a Verity claims
submission frame on (NPI, Rx, Fill).  Produces four sections:

1. Summary (total rows, hits, misses, hit rate).
2. Coverage broken out by pharmacy location.
3. Coverage broken out by transaction code, ordered by miss volume.
4. Miss diagnosis — partition misses by whether the (NPI, Rx) pair is
   present in Verity at all, which isolates fill-number drift from
   outright absence.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon.constants import (
    BEACON_COL_PHARMACY_NPI,
    BEACON_COL_TXN_CODE,
    NPI_TO_SHEET,
    TRANSACTION_CODE_DESCRIPTIONS,
)
from beacon.reports._common import location_name
from beacon.verity_coverage import (
    beacon_npi_rx_pair,
    verity_hit_mask,
    verity_npi_rx_pair_set,
)


def _summary_section(total: int, hits: int, misses: int) -> list[str]:
    """Header + top-line counts for the Verity coverage report."""
    hit_rate: float = (hits / total) if total > 0 else 0.0
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  VERITY CLAIMS OVERLAP")
    lines.append("=" * 80)
    lines.append("")
    lines.append("  A Beacon row is a HIT when its (Pharmacy NPI, Rx Num, Fill Num)")
    lines.append("  triple appears in the Verity claims submission file, keyed as:")
    lines.append("")
    lines.append("    Pharmacy NPI -> Service Provider ID")
    lines.append("    Rx Num       -> Rx Number")
    lines.append("    Fill Num     -> Fill Number")
    lines.append("")
    lines.append("  SUMMARY")
    lines.append("  " + "-" * 40)
    lines.append(f"  Beacon rows (enriched): {total}")
    lines.append(f"  Hits:                   {hits}")
    lines.append(f"  Misses:                 {misses}")
    lines.append(f"  Hit rate:               {hit_rate:.4%}")
    lines.append("")
    lines.append("")
    return lines


def _by_location_section(
    enriched: pd.DataFrame,
    hit_mask: pd.Series,
) -> list[str]:
    """Per-location hit / miss / hit-rate table."""
    locations: list[str] = list(NPI_TO_SHEET.keys())
    loc_names: list[str] = [location_name(n) for n in locations]
    name_width: int = max((len(n) for n in loc_names), default=10)

    lines: list[str] = []
    lines.append("  COVERAGE BY LOCATION")
    lines.append("  " + "-" * 40)
    lines.append("")
    header: str = (
        f"  {'Location':<{name_width}s}  "
        f"{'Rows':>6s}  {'Hits':>6s}  {'Misses':>7s}  {'Hit rate':>9s}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for npi, name in zip(locations, loc_names, strict=True):
        loc_mask: pd.Series = enriched[BEACON_COL_PHARMACY_NPI] == npi
        rows: int = int(loc_mask.sum())
        loc_hits: int = int((hit_mask & loc_mask).sum())
        loc_misses: int = rows - loc_hits
        rate: float = (loc_hits / rows) if rows > 0 else 0.0
        lines.append(
            f"  {name:<{name_width}s}  "
            f"{rows:>6d}  {loc_hits:>6d}  {loc_misses:>7d}  {rate:>8.2%}"
        )
    lines.append("")
    lines.append("")
    return lines


def _by_transaction_code_section(
    enriched: pd.DataFrame,
    hit_mask: pd.Series,
) -> list[str]:
    """Per-transaction-code hit / miss / hit-rate table sorted by miss count desc."""
    codes: list[str] = sorted(enriched[BEACON_COL_TXN_CODE].dropna().unique())
    desc_map: dict[str, str] = {
        c: TRANSACTION_CODE_DESCRIPTIONS.get(c, "") for c in codes
    }
    desc_width: int = max(
        (len(desc_map[c]) for c in codes),
        default=11,
    )
    desc_width = max(desc_width, 11)

    # Precompute per-code counts so we can sort by miss volume descending.
    rows_per_code: dict[str, tuple[int, int, int]] = {}
    for code in codes:
        code_mask: pd.Series = enriched[BEACON_COL_TXN_CODE] == code
        rows: int = int(code_mask.sum())
        code_hits: int = int((hit_mask & code_mask).sum())
        code_misses: int = rows - code_hits
        rows_per_code[code] = (rows, code_hits, code_misses)

    ordered: list[str] = sorted(
        codes,
        key=lambda c: (-rows_per_code[c][2], c),
    )

    lines: list[str] = []
    lines.append("  COVERAGE BY TRANSACTION CODE")
    lines.append("  " + "-" * 40)
    lines.append("  Ordered by miss count (descending).")
    lines.append("")
    header: str = (
        f"  {'Code':<5s}  {'Description':<{desc_width}s}  "
        f"{'Rows':>6s}  {'Hits':>6s}  {'Misses':>7s}  {'Hit rate':>9s}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for code in ordered:
        rows, code_hits, code_misses = rows_per_code[code]
        rate: float = (code_hits / rows) if rows > 0 else 0.0
        lines.append(
            f"  {code:<5s}  {desc_map[code]:<{desc_width}s}  "
            f"{rows:>6d}  {code_hits:>6d}  {code_misses:>7d}  {rate:>8.2%}"
        )
    lines.append("")
    lines.append("")
    return lines


def _miss_diagnosis_section(
    enriched: pd.DataFrame,
    hit_mask: pd.Series,
    verity_df: pd.DataFrame,
) -> list[str]:
    """Break misses down by whether (NPI, Rx) alone matches Verity.

    ``NPI+Rx in Verity`` means only the Fill Number differs (refill-count
    drift, reversal pair, etc.).  ``NPI+Rx NOT in Verity`` means Verity
    does not know about this prescription at that pharmacy at all.
    """
    lines: list[str] = []
    lines.append("  MISS DIAGNOSIS")
    lines.append("  " + "-" * 40)
    lines.append("  Of the misses, how many at least share a (Pharmacy NPI, Rx Num)")
    lines.append("  pair with some Verity row?  A loose-match hit here isolates")
    lines.append("  Fill Number drift from outright absence in Verity.")
    lines.append("")

    miss_rows: pd.DataFrame = enriched.loc[~hit_mask]
    total_misses: int = len(miss_rows)
    if total_misses == 0:
        lines.append("  No misses to diagnose.")
        lines.append("")
        lines.append("=" * 80)
        lines.append("")
        return lines

    verity_pairs: set[tuple[str, str]] = verity_npi_rx_pair_set(verity_df)

    pair_hit_count: int = 0
    pair_miss_count: int = 0
    pair_unparseable: int = 0
    for _, row in miss_rows.iterrows():
        pair: tuple[str, str] | None = beacon_npi_rx_pair(row)
        if pair is None:
            pair_unparseable += 1
        elif pair in verity_pairs:
            pair_hit_count += 1
        else:
            pair_miss_count += 1

    def pct(n: int) -> float:
        return (n / total_misses) if total_misses > 0 else 0.0

    lines.append(f"  Total misses:                       {total_misses}")
    lines.append(
        f"  (NPI, Rx) present in Verity:        "
        f"{pair_hit_count:>6d}  ({pct(pair_hit_count):>7.2%}) "
        "  <- Fill Number differs"
    )
    lines.append(
        f"  (NPI, Rx) absent from Verity:       "
        f"{pair_miss_count:>6d}  ({pct(pair_miss_count):>7.2%}) "
        "  <- not in Verity at all"
    )
    if pair_unparseable > 0:
        lines.append(
            f"  Unparseable NPI or Rx in Beacon row:"
            f"{pair_unparseable:>6d}  ({pct(pair_unparseable):>7.2%}) "
            "  <- cannot form a join key"
        )
    lines.append("")
    lines.append("=" * 80)
    lines.append("")
    return lines


def write_verity_coverage_report(
    enriched: pd.DataFrame,
    verity_df: pd.DataFrame,
    path: Path,
) -> None:
    """Write the Verity claims overlap report.

    Parameters:
        enriched: Enriched Beacon frame with ``Pharmacy NPI``, ``Rx Num``,
                  ``Fill Num``, and ``Transaction Code`` columns.
        verity_df: Verity claims submission frame from
                   :func:`beacon.processing.load_verity_claims_submission`.
        path: Output file path.
    """
    hit_mask: pd.Series = verity_hit_mask(enriched, verity_df)
    total: int = len(enriched)
    hits: int = int(hit_mask.sum())
    misses: int = total - hits

    lines: list[str] = []
    lines += _summary_section(total, hits, misses)
    lines += _by_location_section(enriched, hit_mask)
    lines += _by_transaction_code_section(enriched, hit_mask)
    lines += _miss_diagnosis_section(enriched, hit_mask, verity_df)

    path.write_text("\n".join(lines), encoding="utf-8")
