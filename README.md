# Beacon

Python tools for **Beacon rebate full-load** Excel workbooks. The pipeline:

1. **Deduplicates** prescription transaction rows that belong to the same electronic-switch “chain” by following **ICN** ↔ **Xref** links (resubmissions).
2. **Keeps** only the **head** of each chain: the row whose `ICN` never appears in column `Xref` on another row (the non-superseded transaction).
3. **Joins** MTF fields (`Rx Num`, `Fill Num`) from per-pharmacy sheets in the same workbook.
4. **Writes** text reports and a filtered Excel file for downstream analysis.

Cross-reference chains happen when a prescription is submitted through the switch more than once: a new row gets a new `ICN` in column 1, and the previous `ICN` appears in `Xref` on that row. Tracing those links recovers one chain per prescription; only the final ICN in that chain is retained.

---

## Requirements

| Item | Notes |
|------|--------|
| Python | **3.13+** (`requires-python` in `pyproject.toml`) |
| Dependencies | **pandas**, **openpyxl** — declared in `pyproject.toml` |
| Tooling | [uv](https://docs.astral.sh/uv/) recommended for installs and `uv run` |

### Install from the repository root

Run install commands from the directory that contains **`pyproject.toml`** and **`uv.lock`** (the repo root), not the inner `beacon/` package folder.

```bash
cd path/to/beacon
uv sync
```

`uv sync` creates or updates `.venv`, installs the package in editable mode, and registers the **`beacon`** console script when you use `uv run`.

```bash
pip install -e .
```

works as well if you prefer pip.

---

## Input files

### Primary workbook (`Beacon_Full_Load.xlsx` or your path)

Expected structure:

1. **First sheet** — One row per transaction, with at least:
   - **`ICN`** — claim / interchange control number (column 1 in the business sense).
   - **`Xref`** — cross-reference to a superseded ICN when the prescription was resubmitted; empty when none.
   - **`Transaction Code`**
   - **`Pharmacy NPI`** — must match one of the keys used for MTF routing (see below).

2. **MTF sheets** — One sheet per pharmacy location, named in code via NPI:

   | Pharmacy NPI | Sheet name |
   |--------------|------------|
   | `1073835591` | `MTF - Specialty` |
   | `1194345199` | `MTF - CDA` |
   | `1235986290` | `MTF - Hayden` |
   | `1487401451` | `MTF - Post Falls` |

   Each MTF sheet must include **`ICN`**, **`Rx Num`**, and **`Fill Num`**.

**Leading zeros:** Excel often strips leading zeros from numeric-looking IDs. The pipeline normalises **ICN** to 15 characters and **Rx Num** to 12 where applicable so values line up across sheet 1 and MTF sheets.

**Transaction descriptions:** Short labels for each **Transaction Code** come from the static mapping **`TRANSACTION_CODE_DESCRIPTIONS`** in **`beacon.constants`** (not from an external file). Edit that dict if MFP adds or renames codes.

---

## Running the pipeline

### CLI (recommended)

From the repo root after `uv sync`:

```bash
uv run beacon
```

With **no positional argument**, the input defaults to **`Beacon_Full_Load.xlsx` in the project root** (resolved via `beacon.paths.PROJECT_ROOT`). That file must exist, or pass an explicit path:

```bash
uv run beacon path/to/Beacon_Full_Load.xlsx
uv run beacon C:\data\Beacon_Full_Load.xlsx
```

Write outputs to a specific directory (default: same folder as the input file):

```bash
uv run beacon -o ./out
uv run beacon path/to/in.xlsx -o ./reports
```

Equivalent module invocation:

```bash
uv run python -m beacon
uv run python -m beacon path/to/Beacon_Full_Load.xlsx -o ./out
```

If your shell is **not** in the repo root, point uv at the project:

```bash
uv run --project path/to/beacon-repo beacon path/to/Beacon_Full_Load.xlsx
```

Or set **`UV_PROJECT`** to that directory. On Windows you can use full paths for both `--project` and the input file.

### Programmatic use

```python
from pathlib import Path

from beacon import run

run(Path("Beacon_Full_Load.xlsx"))
run(Path("workbook.xlsx"), output_dir=Path("./out"))
```

---

## Outputs

Unless `-o` / `output_dir` is set, files are written next to the **input** workbook.

| File | Description |
|------|-------------|
| **`Xref_Chain_Report.txt`** | Every multi-step chain with spreadsheet row numbers (1-based) and a summary (totals, chain-length distribution). |
| **`ICN_Retained.txt`** | One retained **ICN** per chain (the head only), sorted by chain length. |
| **`Beacon_Analytics.txt`** | Summary stats, transaction codes by location, chain stats by pharmacy, Rx/Fill analysis. |
| **`BeaconT2.xlsx`** | Filtered **retained** rows with MTF columns joined and **Transaction Description** from the built-in code lookup. |

Output basenames and the transaction-code map live in **`beacon.constants`** (`XREF_CHAIN_REPORT_FILE`, `TRANSACTION_CODE_DESCRIPTIONS`, etc.).

---

## Verification helper

**`beacon.verify_mtf`** checks that every retained ICN from sheet 1 appears on the correct MTF sheet for its pharmacy NPI (same normalisation rules as the main pipeline).

```bash
uv run python -m beacon.verify_mtf
```

Defaults to **`Beacon_Full_Load.xlsx`** in the project root; returns exit code **0** when all ICNs match, **1** otherwise. Import `verify` from `beacon.verify_mtf` if you need a boolean in code.

---

## Project layout

```
beacon/                      # repository root
  pyproject.toml
  uv.lock
  beacon/                    # Python package
    __init__.py              # public exports
    __main__.py              # python -m beacon
    cli.py                   # argparse; console entry point `beacon`
    constants.py             # required columns, filenames, NPI → MTF, tx code labels
    paths.py                 # PROJECT_ROOT
    pipeline.py              # run() — orchestration only
    processing.py            # load, chains, MTF join, Excel export
    reports.py               # text reports (chains, retained ICNs, analytics)
    verify_mtf.py            # MTF presence check for retained ICNs
```

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| **`input file not found`** | Pass the full path to the full-load `.xlsx`, or place **`Beacon_Full_Load.xlsx`** in the repo root when using the default. |
| **`ImportError: attempted relative import with no known parent package`** | Prefer **`uv run python -m beacon`** or **`uv run beacon`** from the repo root. Avoid running `beacon/cli.py` as a loose script unless the repo is on `PYTHONPATH`; the package is meant to run as a module or installed console script. |
| **Missing `Pharmacy NPI` or MTF sheet** | Use a true full-load export with sheet 1 + MTF tabs; partial extracts may not match `REQUIRED_COLUMNS` or `NPI_TO_SHEET`. |

---

## License

Add a license if you distribute this repository.
