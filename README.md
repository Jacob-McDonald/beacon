# Beacon

Python tools for **Beacon rebate full-load** Excel workbooks. The pipeline:

1. **Deduplicates** prescription transaction rows that belong to the same electronic-switch “chain” by following **ICN** ↔ **Xref** links (resubmissions).
2. **Keeps** only the **head** of each chain: the row whose `ICN` never appears in column `Xref` on another row (the non-superseded transaction).
3. **Joins** MTF fields (`Rx Num`, `Fill Num`) from per-pharmacy sheets in the same workbook.
4. **(Optional) Verity claims overlap** — compares `(Pharmacy NPI, Rx Num, Fill Num)` triples against a Verity claims-submission rollup and reports hits/misses with per-location and per-transaction-code breakdowns.
5. **(Optional) Verity_Matches enrichment** — filters Verity_Matches exports to the four pharmacy NPIs, audits `Eligible == YES` `(Rx, Fill)` duplicates, and appends a `Verity_Matches` YES/NO column to the filtered Beacon export.
6. **Writes** text reports (under `reports/`) and a filtered Excel file for downstream analysis.

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

### Optional Verity inputs

Two independent optional inputs plug into the pipeline. Both read the enriched Beacon frame **in memory** — no second pass over `Beacon_Filtered.xlsx`.

| Flag | Input shape | Purpose |
|------|-------------|---------|
| `-v` / `--verity` | Single `Verity_Claims_Submission*.xlsx` rollup (sheet **`Verity_Claims_Submission`**, columns `Service Provider ID`, `Rx Number`, `Fill Number`). | Hit/miss overlap stats against Beacon `(Pharmacy NPI, Rx Num, Fill Num)` triples. |
| `-m` / `--verity-matches` | Either a single through-range `.xlsx` or a **folder** of monthly `*_Verity_Matches.xlsx` files (sheet **`New Matches`**, columns `Match NPI`, `Eligible`, `Rx Number`, `Disp Fill #`). | Pharmacy-NPI filter, `Eligible=YES` dupe audit, and a `Verity_Matches` YES/NO column on the filtered Beacon export. |

Monthly Verity_Matches files are expected to follow the `Mon_YYYY_Verity_Matches.xlsx` naming pattern (e.g. `Apr_2026_Verity_Matches.xlsx`); they are loaded and concatenated in calendar order.

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

Each run writes its artifacts into a dated subfolder named `<input-stem>_<YYYY-MM-DD>` underneath the base output directory. The default base is an `output/` folder next to the input workbook; override with `-o`:

```bash
uv run beacon -o ./out
uv run beacon path/to/in.xlsx -o ./reports
```

Re-running on the same input on the same day overwrites the previous run's files.

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

### IDE entry point (`main.py`)

`main.py` at the repo root is a thin shim that calls `runpy.run_module("beacon", run_name="__main__")`. It exists so IDE run configurations (VS Code, PyCharm) that default to launching a top-level script still exercise the same code path as `python -m beacon`. Arguments supplied through the IDE's "run" form are forwarded verbatim. For any non-IDE use, **`uv run beacon`** or **`uv run python -m beacon`** is the canonical invocation.

### Verity claims overlap (`-v` / `--verity`)

Pass a Verity claims-submission rollup and the pipeline will compute hit/miss statistics against the enriched Beacon frame, write a `Verity_Coverage.txt` diagnostic, and print the headline numbers:

```bash
uv run beacon -v verity_claims/Verity_Claims_Submission_Oct_2025_thru_Apr_2026.xlsx
```

Module form:

```bash
uv run python -m beacon -v verity_claims/Verity_Claims_Submission_Oct_2025_thru_Apr_2026.xlsx
```

A Beacon row counts as a **hit** when at least one Verity row shares the same `(Pharmacy NPI → Service Provider ID, Rx Num → Rx Number, Fill Num → Fill Number)` triple. The report breaks misses down by pharmacy location and transaction code, and includes a loose-match diagnosis (misses whose `(NPI, Rx)` pair *does* exist in Verity but at a different Fill Number, vs. misses where `(NPI, Rx)` is absent entirely).

### Verity_Matches enrichment (`-m` / `--verity-matches`)

Accepts either a single `.xlsx` or a folder of monthly files. The pipeline filters every input to the four pharmacy NPIs, writes a combined `Verity_Matches_Filtered.xlsx` next to the inputs, audits `Eligible == YES` `(Rx, Fill)` duplicates (warn-only, never fails), and appends a `Verity_Matches` YES/NO column to `Beacon_Filtered.xlsx`.

Folder form (recommended — calendar-sorted concatenation):

```bash
uv run beacon -m verity_matches/
```

Single-file form:

```bash
uv run beacon -m verity_matches/Verity_Matches_Oct_2025_thru_Apr_2026.xlsx
```

Combined with Verity overlap (typical full run):

```bash
uv run beacon \
    -v verity_claims/Verity_Claims_Submission_Oct_2025_thru_Apr_2026.xlsx \
    -m verity_matches/
```

Module form:

```bash
uv run python -m beacon -v verity_claims/Verity_Claims_Submission_Oct_2025_thru_Apr_2026.xlsx -m verity_matches/
```

### Programmatic use

The pipeline takes a `PipelineConfig` and returns a `PipelineResult` describing every artifact it produced:

```python
from pathlib import Path

from beacon import PipelineConfig, run

result = run(PipelineConfig(input_path=Path("Beacon_Full_Load.xlsx")))

result = run(PipelineConfig(
    input_path=Path("workbook.xlsx"),
    output_dir=Path("./out"),
))

result = run(PipelineConfig(
    input_path=Path("Beacon_Full_Load.xlsx"),
    verity_path=Path("verity_claims/Verity_Claims_Submission_Oct_2025_thru_Apr_2026.xlsx"),
    verity_matches_path=Path("verity_matches"),
))

print(result.filtered_excel)            # Path to Beacon_Filtered.xlsx
print(result.chain_report)               # always present
print(result.verity_coverage_report)     # Path or None (only set with verity_path)
print(result.verity_matches_report)      # Path or None (only set with verity_matches_path)
print(result.filtered_verity_matches)    # Path or None (only set with verity_matches_path)
print(result.verity_matches_yes, result.verity_matches_no)  # None unless -m was set
```

Pipeline progress is logged through `logging.getLogger("beacon")`. The CLI installs a plain-text handler on that logger at `INFO` level (use `-q` / `--quiet` to suppress everything except warnings). Library callers can attach their own handler instead for JSON output, log rotation, etc.

---

## Outputs

Each run lands in `<base>/<input-stem>_<YYYY-MM-DD>/` where `<base>` is `<input_parent>/output/` by default or whatever you pass to `-o` / `output_dir`. Text reports live under a `reports/` sub-subfolder; the filtered Excel export stays at the top of the run directory because it is the primary data product. Re-running on the same input on the same day overwrites the previous run's files. Example layout:

```
output/
  Beacon_Full_Load_2026-05-13/
    Beacon_Filtered.xlsx
    reports/
      Xref_Chain_Report.txt
      ICN_Retained.txt
      Beacon_Analytics.txt
      Rx_Fill_Duplicate_Patterns.txt
      Rx_Fill_Duplicate_Groups.txt
```

The exported `Beacon_Filtered.xlsx` (and `Verity_Matches_Filtered.xlsx` when `-m` is set) has its header row frozen and column widths auto-sized to the longer of the header and the widest cell value (capped at 50 chars).

### Excel artifacts (top-level)

| File | Description |
|------|-------------|
| **`Beacon_Filtered.xlsx`** | Filtered **retained** rows with MTF columns joined, **Transaction Description** from the built-in code lookup, and (when `-m` is set) a **`Verity_Matches`** YES/NO column. |
| **`verity_matches/Verity_Matches_Filtered.xlsx`** *(only with `-m`)* | Pharmacy-NPI-filtered, calendar-ordered concatenation of the input Verity_Matches file(s). Basename for single-file inputs is `<stem>_Filtered.xlsx` written alongside the source. |

### Text reports (`reports/`)

| File | Written when | Description |
|------|--------------|-------------|
| **`Xref_Chain_Report.txt`** | always | Every multi-step chain with spreadsheet row numbers (1-based) and a summary (totals, chain-length distribution). |
| **`ICN_Retained.txt`** | always | One retained **ICN** per chain (the head only), sorted by chain length. |
| **`Beacon_Analytics.txt`** | always | Summary stats, transaction codes by location, chain stats by pharmacy, Rx/Fill analysis. |
| **`Rx_Fill_Duplicate_Patterns.txt`** | always | `(Rx, Fill)` duplicate pattern summary across retained rows. |
| **`Rx_Fill_Duplicate_Groups.txt`** | always | Per-group detail for each `(Rx, Fill)` duplicate pattern. |
| **`Verity_Coverage.txt`** | `-v` | Hit/miss totals + per-location + per-transaction-code breakdowns + loose-match miss diagnosis. |
| **`Verity_Matches.txt`** | `-m` | Per-source row counts, `Eligible=YES` duplicate audit (count + sample), and `Verity_Matches` YES/NO totals. |
| **`Verity_Matches_Duplicates.txt`** | `-m` | One section per `(NPI, Rx, Fill)` duplicate group among `Eligible=YES` rows: side-by-side `[same]`/`[DIFF]` field dump plus a rules-based cause diagnosis. Always written (empty-body when no groups). |

Output basenames and the transaction-code map live in **`beacon.constants`** (`XREF_CHAIN_REPORT_FILE`, `VERITY_COVERAGE_REPORT_FILE`, `VERITY_MATCHES_REPORT_FILE`, `TRANSACTION_CODE_DESCRIPTIONS`, etc.).

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
  main.py                    # IDE shim: runs `python -m beacon` via runpy (see below)
  beacon/                    # Python package
    __init__.py              # public exports
    __main__.py              # python -m beacon
    cli.py                   # argparse + logging config; console entry point `beacon`
    constants.py             # column names, filenames, NPI → MTF, tx code labels (tuples/frozensets)
    keys.py                  # (ICN, NPI, Rx, Fill) join-key normalisation
    paths.py                 # PROJECT_ROOT
    pipeline.py              # run(), PipelineConfig, PipelineResult — orchestration only
    processing.py            # load, chains, MTF join, Excel export
    reports/                 # text report writers (one submodule per report family)
      __init__.py            # re-exports every write_* function
      _common.py             # location_name helper shared across reports
      chains.py              # Xref_Chain_Report.txt + ICN_Retained.txt
      analytics.py           # Beacon_Analytics.txt
      duplicates.py          # Rx_Fill_Duplicate_Patterns.txt + Rx_Fill_Duplicate_Groups.txt
      verity_coverage.py     # Verity_Coverage.txt
      verity_matches.py      # Verity_Matches.txt
    verify_mtf.py            # MTF presence check for retained ICNs
    verity_coverage.py       # (NPI, Rx, Fill) overlap stats against Verity claims submission
    verity_matches.py        # Verity_Matches load/filter/dedupe audit + YES/NO enrichment
```

---

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| **`input file not found`** | Pass the full path to the full-load `.xlsx`, or place **`Beacon_Full_Load.xlsx`** in the repo root when using the default. |
| **`ImportError: attempted relative import with no known parent package`** | Prefer **`uv run python -m beacon`** or **`uv run beacon`** from the repo root. Avoid running `beacon/cli.py` as a loose script unless the repo is on `PYTHONPATH`; the package is meant to run as a module or installed console script. |
| **Missing `Pharmacy NPI` or MTF sheet** | Use a true full-load export with sheet 1 + MTF tabs; partial extracts may not match `REQUIRED_COLUMNS` or `NPI_TO_SHEET`. |
| **`verity file not found`** | `-v` expects a single `.xlsx`. Double-check the path; on Windows quote the path if it contains spaces. |
| **`verity-matches path not found`** or **`No files matching '*_Verity_Matches.xlsx'`** | `-m` accepts a single file **or** a directory. For folder input, every file must end in `_Verity_Matches.xlsx` (e.g. `Apr_2026_Verity_Matches.xlsx`). |
| **`missing required columns [...]` from a Verity_Matches file** | The pipeline reads the `New Matches` sheet and requires `Match NPI`, `Eligible`, `Rx Number`, `Disp Fill #`. Re-export the month(s) with the standard header row. |

---

## License

Add a license if you distribute this repository.
