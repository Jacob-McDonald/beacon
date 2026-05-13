"""Tests for the Rx/Fill duplicate report's (NPI, Rx, Fill) key."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from beacon.reports.duplicates import write_duplicate_reports


def _enriched(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype="string")


def _empty_full_df() -> pd.DataFrame:
    return pd.DataFrame(
        {"ICN": pd.Series(dtype="string"), "Transaction Code": pd.Series(dtype="string")},
    )


def test_same_rx_fill_under_different_npis_is_not_a_duplicate(tmp_path: Path):
    """Rx numbers are per-pharmacy; a shared (Rx, Fill) across NPIs must not group."""
    enriched = _enriched([
        {"ICN": "A", "Pharmacy NPI": "1073835591", "Rx Num": "100", "Fill Num": "0",
         "Transaction Code": "001"},
        {"ICN": "B", "Pharmacy NPI": "1194345199", "Rx Num": "100", "Fill Num": "0",
         "Transaction Code": "001"},
    ])

    patterns: Path = tmp_path / "patterns.txt"
    groups: Path = tmp_path / "groups.txt"
    write_duplicate_reports(enriched, [], _empty_full_df(), patterns, groups)

    # No group should have been emitted — same Rx/Fill under different NPIs
    # is not a duplicate.
    body: str = groups.read_text()
    assert "Total duplicate groups: 0" in body


def test_same_rx_fill_within_one_npi_is_a_duplicate(tmp_path: Path):
    """Two retained rows for the same pharmacy with same (Rx, Fill) DO form a dup."""
    enriched = _enriched([
        {"ICN": "A", "Pharmacy NPI": "1073835591", "Rx Num": "100", "Fill Num": "0",
         "Transaction Code": "001"},
        {"ICN": "B", "Pharmacy NPI": "1073835591", "Rx Num": "100", "Fill Num": "0",
         "Transaction Code": "001"},
    ])
    # build_chains has not been called, but write_duplicate_reports falls back
    # to ICN -> Transaction Code via full_df when an ICN is not a chain head.
    full_df = pd.DataFrame(
        {
            "ICN": ["A", "B"],
            "Transaction Code": ["001", "001"],
        },
        dtype="string",
    )

    patterns: Path = tmp_path / "patterns.txt"
    groups: Path = tmp_path / "groups.txt"
    write_duplicate_reports(enriched, [], full_df, patterns, groups)

    body: str = groups.read_text()
    assert "Total duplicate groups: 1" in body
    assert "Rx 100" in body
    assert "Fill 0" in body
