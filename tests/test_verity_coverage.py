"""Unit tests for verity_hit_mask and verity_coverage_stats."""

from __future__ import annotations

import pandas as pd

from beacon.verity_coverage import (
    verity_coverage_stats,
    verity_hit_mask,
)


def _enriched(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype="string")


def _verity(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, dtype="string")


def test_hit_mask_matches_on_npi_rx_fill_triple():
    enriched = _enriched([
        {"Pharmacy NPI": "1073835591", "Rx Num": "100",  "Fill Num": "0"},
        {"Pharmacy NPI": "1073835591", "Rx Num": "200",  "Fill Num": "0"},
        {"Pharmacy NPI": "1194345199", "Rx Num": "100",  "Fill Num": "0"},
    ])
    verity = _verity([
        {"Service Provider ID": "1073835591", "Rx Number": "100", "Fill Number": "0"},
        {"Service Provider ID": "1194345199", "Rx Number": "100", "Fill Number": "0"},
    ])

    mask = verity_hit_mask(enriched, verity)

    assert mask.tolist() == [True, False, True]


def test_hit_mask_normalises_rx_zero_padding():
    """``rx_key`` zero-pads numeric Rx to 12 chars; bare numbers still match."""
    enriched = _enriched([
        {"Pharmacy NPI": "1", "Rx Num": "000000000099", "Fill Num": "1"},
    ])
    # Verity stores the same Rx as a short string; normalisation should align them.
    verity = _verity([
        {"Service Provider ID": "1", "Rx Number": "99", "Fill Number": "1"},
    ])

    assert verity_hit_mask(enriched, verity).tolist() == [True]


def test_hit_mask_skips_rows_with_missing_keys():
    """Beacon rows lacking any of NPI / Rx / Fill cannot form a valid key."""
    enriched = _enriched([
        {"Pharmacy NPI": "",  "Rx Num": "100", "Fill Num": "0"},
        {"Pharmacy NPI": "1", "Rx Num": "",    "Fill Num": "0"},
        {"Pharmacy NPI": "1", "Rx Num": "100", "Fill Num": ""},
    ])
    verity = _verity([
        {"Service Provider ID": "1", "Rx Number": "100", "Fill Number": "0"},
    ])

    assert verity_hit_mask(enriched, verity).tolist() == [False, False, False]


def test_coverage_stats_counts_hits_misses_and_rate():
    enriched = _enriched([
        {"Pharmacy NPI": "1", "Rx Num": "10", "Fill Num": "0"},
        {"Pharmacy NPI": "1", "Rx Num": "20", "Fill Num": "0"},
        {"Pharmacy NPI": "1", "Rx Num": "30", "Fill Num": "0"},
        {"Pharmacy NPI": "1", "Rx Num": "40", "Fill Num": "0"},
    ])
    verity = _verity([
        {"Service Provider ID": "1", "Rx Number": "10", "Fill Number": "0"},
        {"Service Provider ID": "1", "Rx Number": "30", "Fill Number": "0"},
    ])

    stats = verity_coverage_stats(enriched, verity)

    assert stats.beacon_row_count == 4
    assert stats.hits == 2
    assert stats.misses == 2
    assert stats.hit_rate == 0.5


def test_coverage_stats_handles_empty_verity():
    enriched = _enriched([
        {"Pharmacy NPI": "1", "Rx Num": "10", "Fill Num": "0"},
    ])
    verity = _verity([])
    # Provide the expected columns explicitly so the empty frame has the schema.
    verity = pd.DataFrame(
        columns=["Service Provider ID", "Rx Number", "Fill Number"],
        dtype="string",
    )

    stats = verity_coverage_stats(enriched, verity)

    assert stats.hits == 0
    assert stats.misses == 1
    assert stats.hit_rate == 0.0
