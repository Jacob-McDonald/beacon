"""Excel writers for the Beacon pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.utils import get_column_letter


def _autosize_columns(ws, df: pd.DataFrame) -> None:
    """Set each column's width to fit the longer of the header and the
    widest value, capped at 50 characters and floored at 8."""
    for col_idx, col_name in enumerate(df.columns, start=1):
        header_len: int = len(str(col_name))
        value_len: int = 0
        if len(df) > 0:
            max_len = df[col_name].astype("string").str.len().max()
            if pd.notna(max_len):
                value_len = int(max_len)
        width: int = min(max(header_len, value_len, 8) + 2, 50)
        ws.column_dimensions[get_column_letter(col_idx)].width = width


def write_filtered_excel(
    df: pd.DataFrame,
    path: Path,
    *,
    sheet_name: str = "Beacon",
) -> None:
    """Write *df* to *path* with a frozen header row and auto-sized columns.

    Parameters:
        df: DataFrame to export.
        path: Destination ``.xlsx`` file path.  Parent directories are created
              if missing.
        sheet_name: Worksheet name.  Defaults to ``"Beacon"``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        # Freeze everything above row 2 — i.e. lock the header row in place.
        ws.freeze_panes = "A2"
        _autosize_columns(ws, df)
