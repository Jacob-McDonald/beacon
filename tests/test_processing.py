"""Unit tests for chain build, retention filter, and MTF enrichment."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from beacon.processing import (
    build_chains,
    enrich_with_mtf,
    get_retained_df,
    load_transactions,
)


def _sheet1(rows: list[dict]) -> pd.DataFrame:
    """Build a sheet-1-shaped DataFrame from a list of dicts.

    Mirrors what would land in memory after ``load_transactions`` minus
    the ICN zero-padding, which the chain logic doesn't depend on.
    """
    return pd.DataFrame(rows, dtype="string")


# ---------------------------------------------------------------------------
# build_chains
# ---------------------------------------------------------------------------


def test_build_chains_three_link_chain():
    """A→B→C is one chain of depth 3 with head ICN C."""
    df = _sheet1([
        {"ICN": "A", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
        {"ICN": "B", "Xref": "A",  "Transaction Code": "002", "Pharmacy NPI": "1"},
        {"ICN": "C", "Xref": "B",  "Transaction Code": "003", "Pharmacy NPI": "1"},
        {"ICN": "X", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
    ])

    chains = build_chains(df)

    assert len(chains) == 1
    chain = chains[0]
    assert chain.depth == 3
    assert chain.origin_icn == "A"
    assert chain.head_icn == "C"
    assert chain.origin_npi == "1"
    assert chain.txn_codes == ("001", "002", "003")


def test_build_chains_handles_cycle_without_hanging():
    """A cycle is broken with a warning, not an infinite loop."""
    df = _sheet1([
        {"ICN": "O", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
        {"ICN": "P", "Xref": "O",  "Transaction Code": "002", "Pharmacy NPI": "1"},
        {"ICN": "Q", "Xref": "P",  "Transaction Code": "002", "Pharmacy NPI": "1"},
        {"ICN": "P", "Xref": "Q",  "Transaction Code": "002", "Pharmacy NPI": "1"},
    ])

    chains = build_chains(df)

    assert len(chains) >= 1
    for chain in chains:
        icns = [link.icn for link in chain.links]
        assert len(icns) == len(set(icns)), f"chain has repeated ICN: {icns}"


def test_build_chains_skips_standalone_rows():
    """A single submission with no Xref and not superseded is not a chain."""
    df = _sheet1([
        {"ICN": "S", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
        {"ICN": "T", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
    ])

    assert build_chains(df) == []


# ---------------------------------------------------------------------------
# get_retained_df
# ---------------------------------------------------------------------------


def test_get_retained_df_keeps_only_unsuperseded():
    df = _sheet1([
        {"ICN": "A", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
        {"ICN": "B", "Xref": "A",  "Transaction Code": "002", "Pharmacy NPI": "1"},
        {"ICN": "C", "Xref": None, "Transaction Code": "001", "Pharmacy NPI": "1"},
    ])

    retained = get_retained_df(df)

    # A is superseded by B and so dropped; B and C remain.
    assert set(retained["ICN"]) == {"B", "C"}


# ---------------------------------------------------------------------------
# enrich_with_mtf — composite-key join
# ---------------------------------------------------------------------------


def _mtf_lookup(rows: list[dict]) -> pd.DataFrame:
    """Build an MTF lookup indexed by (ICN, Pharmacy NPI) for tests."""
    return pd.DataFrame(rows, dtype="string").set_index(["ICN", "Pharmacy NPI"])


def test_enrich_with_mtf_joins_on_icn_and_npi():
    """Same ICN under two pharmacies produces one row per (ICN, NPI)."""
    retained = pd.DataFrame(
        [
            {"ICN": "X1", "Pharmacy NPI": "NPI_A"},
            {"ICN": "X1", "Pharmacy NPI": "NPI_B"},
        ],
        dtype="string",
    )
    mtf = _mtf_lookup([
        {"ICN": "X1", "Pharmacy NPI": "NPI_A", "Rx Num": "100", "Fill Num": "0"},
        {"ICN": "X1", "Pharmacy NPI": "NPI_B", "Rx Num": "200", "Fill Num": "1"},
    ])

    result = enrich_with_mtf(retained, mtf)

    assert len(result) == 2
    by_npi = dict(zip(result["Pharmacy NPI"], result["Rx Num"]))
    assert by_npi == {"NPI_A": "100", "NPI_B": "200"}


def test_enrich_with_mtf_no_row_explosion_on_unrelated_dupes():
    """Duplicate ICNs across NPIs in the lookup do not fan out retained rows."""
    retained = pd.DataFrame(
        [{"ICN": "X1", "Pharmacy NPI": "NPI_A"}],
        dtype="string",
    )
    mtf = _mtf_lookup([
        {"ICN": "X1", "Pharmacy NPI": "NPI_A", "Rx Num": "100", "Fill Num": "0"},
        {"ICN": "X1", "Pharmacy NPI": "NPI_B", "Rx Num": "200", "Fill Num": "1"},
    ])

    result = enrich_with_mtf(retained, mtf)

    assert len(result) == 1
    assert result.iloc[0]["Rx Num"] == "100"


# ---------------------------------------------------------------------------
# load_transactions — missing-column validation
# ---------------------------------------------------------------------------


def test_load_transactions_reports_missing_required_columns(tmp_path: Path):
    """A workbook missing one of REQUIRED_COLUMNS raises ValueError naming it."""
    missing_col_wb: Path = tmp_path / "bad.xlsx"
    # Build a one-row workbook missing the Pharmacy NPI column entirely.
    pd.DataFrame(
        [{"ICN": "A", "Xref": "", "Transaction Code": "001", "Basis of Price": ""}],
    ).to_excel(missing_col_wb, index=False, engine="openpyxl")

    with pytest.raises(ValueError, match="Missing required column"):
        load_transactions(missing_col_wb)
