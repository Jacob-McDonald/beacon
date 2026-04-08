# Beacon

Tools for processing Beacon rebate full-load Excel exports: deduplicate prescription transactions that are linked by **ICN** and **Xref** (resubmission chains), produce text reports, and write a filtered workbook with MTF fields joined in.

## Requirements

- Python **3.13+**
- Dependencies: `pandas`, `openpyxl` (see `pyproject.toml`)

### Where to run install commands

Run **`uv sync`** (and **`pip install -e .`**) from the **repository root**: the folder that contains **`pyproject.toml`** and **`uv.lock`** (alongside the `beacon/` package directory). If you cloned this project, that is the top-level `beacon` project folder, not the inner `beacon/beacon/` Python package.

Example:

```bash
cd path/to/beacon    # directory with pyproject.toml
uv sync
```

`uv` uses the current working directory to find the project; there is no need to `cd` into the inner `beacon/` package folder for sync.

Install with [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv sync
```

This creates or updates `.venv` in that same root, installs the `beacon` package in editable mode, and registers the `beacon` console command when you use `uv run`.

Or with pip (also from the repository root):

```bash
pip install -e .
```

## Input: `Beacon_Full_Load.xlsx`

The workbook is expected to include:

1. **First sheet** — Transaction rows with at least:
   - `ICN`, `Xref`, `Transaction Code`, `Pharmacy NPI`
2. **MTF sheets** (one per pharmacy location), named and mapped by NPI:
   - `1073835591` → `MTF - Specialty`
   - `1194345199` → `MTF - CDA`
   - `1235986290` → `MTF - Hayden`
   - `1487401451` → `MTF - Post Falls`

Each MTF sheet must include `ICN`, `Rx Num`, and `Fill Num`.

**Note:** Excel often stores long numeric IDs without leading zeros. The pipeline zero-pads **ICN** to 15 characters and **Rx Num** to 12 so values align with sheet 1 and stay a consistent width in output.

## Running the pipeline

**Chain logic:** A row is **retained** if its `ICN` never appears as another row’s `Xref` (it was not superseded). Multi-row chains are listed in reports; only the head of each chain survives in the filtered file.

After `uv sync` from the repository root, you can run the pipeline from **any** directory. Paths to the `.xlsx` can be absolute or relative.

**If your shell is not in the repo root**, `uv` will not find `pyproject.toml` by walking up from the current folder. Point at the project explicitly with **`--project`** (path to the directory that contains `pyproject.toml` and `uv.lock`):

```bash
uv run --project path/to/beacon-repo beacon path/to/Beacon_Full_Load.xlsx
```

```bash
uv run --project path/to/beacon-repo python -m beacon path/to/Beacon_Full_Load.xlsx
```

On Windows, use a full path if you like: `uv run --project C:\Users\you\python-projects\beacon beacon C:\...\Beacon_Full_Load.xlsx`.

You can also set the environment variable **`UV_PROJECT`** to that same directory instead of passing `--project` each time.

Using **`uv run`** from the repo root (after `cd`) is the usual shortcut so `--project` is unnecessary.

Use either the **console script** or **`python -m`** (same CLI):

```bash
uv run beacon path/to/Beacon_Full_Load.xlsx
```

```bash
uv run python -m beacon path/to/Beacon_Full_Load.xlsx
```

Write outputs somewhere other than next to the input:

```bash
uv run beacon path/to/Beacon_Full_Load.xlsx -o ./out
```

```bash
uv run python -m beacon path/to/Beacon_Full_Load.xlsx -o ./out
```

If the environment already has the package installed, you can omit `uv run`:

```bash
beacon path/to/Beacon_Full_Load.xlsx
python -m beacon path/to/Beacon_Full_Load.xlsx
```

### Programmatic use

```python
from pathlib import Path
from beacon import run

run(Path("Beacon_Full_Load.xlsx"))
```

### Outputs (default filenames, next to input unless `-o` is set)

| File | Description |
|------|-------------|
| `Xref_Chain_Report.txt` | Chains with row numbers and a summary |
| `ICN_Retained.txt` | Retained ICN from each chain (head of chain only) |
| `BeaconT2.xlsx` | Filtered rows plus `Rx Num` and `Fill Num` from the matching MTF sheet |

## Helper modules

| Module | Purpose |
|--------|---------|
| `beacon.verify_mtf` | Confirms every retained ICN exists on the correct MTF sheet. `verify(path=...)` returns `True`/`False`. |
| `beacon.icn_by_location` | Writes `ICN_By_Location.txt` in the project root — retained ICNs grouped by MTF / pharmacy NPI. |

Run from the repo (paths default to `Beacon_Full_Load.xlsx` in the project root):

```bash
uv run python -m beacon.verify_mtf
uv run python -m beacon.icn_by_location
```

## Project layout

```
beacon/                    # repository root
  pyproject.toml
  beacon/                  # Python package
    __init__.py
    __main__.py            # enables: python -m beacon
    cli.py                 # argparse; also exposed as console script `beacon`
    constants.py           # column names, output filenames, NPI → sheet map
    paths.py               # PROJECT_ROOT for helper scripts
    pipeline.py            # run() only — orchestrates the workflow
    processing.py          # chains, MTF enrichment, Excel export
    reports.py             # text reports (chains, retained ICNs, analytics)
    verify_mtf.py
    icn_by_location.py
```

## License

Add a license if you distribute this repo.
