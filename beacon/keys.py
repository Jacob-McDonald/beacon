"""Join-key normalisation for Beacon / MTF / Verity comparisons.

This module is the single source of truth for the string arithmetic that
maps Excel-origin cells into deterministic join keys.  Every pipeline
component that compares ``ICN``, ``Pharmacy NPI``, ``Rx Num``, or
``Fill Num`` against another source must go through these functions so
one definition of "same value" applies end-to-end.

+------------------+-------------------+----------------------------------------+
| Key              | Return type       | Rule                                   |
+==================+===================+========================================+
| icn_key          | ``str``           | stripped string, zero-padded to 15     |
| npi_key          | ``str``           | stripped string; empty when NaN        |
| rx_key           | ``str``           | 12-char zero-padded; empty when NaN    |
| fill_key         | ``int | None``    | rounded int; ``None`` when unparseable |
| icn_key_series   | ``Series[str]``   | vectorised :func:`icn_key`             |
| npi_key_series   | ``Series[str]``   | vectorised :func:`npi_key`             |
| rx_key_series    | ``Series[str]``   | vectorised :func:`rx_key`              |
| fill_key_series  | ``Series[Int64]`` | vectorised :func:`fill_key`; ``NA``    |
+------------------+-------------------+----------------------------------------+

Rationale: Excel routinely strips leading zeros from numeric-looking IDs
and silently converts integer-valued columns to floats (``50037125.0``).
Normalising at every comparison boundary is the only way to keep the
join stable across sheet re-exports.
"""

from __future__ import annotations

import pandas as pd

__all__ = [
    "canonical_icn_series",
    "fill_key",
    "fill_key_series",
    "icn_key",
    "icn_key_series",
    "npi_key",
    "npi_key_series",
    "rx_key",
    "rx_key_series",
]


def icn_key(value: object) -> str:
    """Normalise an ICN cell to a 15-char zero-padded string.

    Parameters:
        value: Raw cell content.  Pandas ``NA`` / ``NaN`` / ``None``
               return an empty string; everything else is coerced via
               ``str()`` then padded.

    Returns:
        A 15-character string, or ``""`` for missing values.  ICNs that
        are already 15 chars are returned unchanged.
    """
    if pd.isna(value):
        return ""
    return str(value).strip().zfill(15)


def npi_key(value: object) -> str:
    """Normalise a Pharmacy NPI cell to a stripped string.

    Parameters:
        value: Raw cell content.

    Returns:
        The stripped string form, or ``""`` when the cell is missing.
    """
    if pd.isna(value):
        return ""
    return str(value).strip()


def rx_key(value: object) -> str:
    """12-char zero-padded Rx key; stripped string when not numeric.

    Handles Excel's habit of storing numeric Rx numbers as floats
    (``50037125.0``) by rounding through int before padding.  Matches the
    12-char canonical form used in MTF sheets after the zero-padding pass.

    Parameters:
        value: Raw cell content.

    Returns:
        A 12-character string when *value* is numeric-looking; the
        stripped non-numeric form otherwise (Rx values in some sources
        contain letters; both sides use the same spelling so a verbatim
        comparison still matches).  Returns ``""`` when *value* is NaN.
    """
    if pd.isna(value):
        return ""
    try:
        whole: int = int(round(float(str(value))))
    except (TypeError, ValueError):
        # Non-numeric Rx: fall back to the stripped string form.  A
        # purely digit string would already have been parsed as float
        # above, so anything that lands here contains at least one
        # non-digit and must not be zero-padded.
        return str(value).strip()
    return str(whole).zfill(12)


def icn_key_series(s: pd.Series) -> pd.Series:
    """Vectorised :func:`icn_key`: strip and zero-pad to 15 chars.

    Preserves ``NA`` cells.  Mirrors the scalar ``icn_key`` semantics for
    ``StringDtype`` columns so call sites can drop ``.apply(icn_key)``.

    Parameters:
        s: String series (typically ``StringDtype``) of raw ICN values.

    Returns:
        A new series of the same length with every non-null cell
        stripped and left-padded to 15 characters.

    Note:
        Whitespace-only cells pad to ``"000000000000000"`` — identical to
        the scalar :func:`icn_key`.  Use :func:`canonical_icn_series` at
        load time when that behaviour would mask missing data.
    """
    return s.str.strip().str.zfill(15)


def canonical_icn_series(s: pd.Series) -> pd.Series:
    """Load-time canonical ICN series: strip, coerce empty-to-NA, zero-pad.

    The one difference from :func:`icn_key_series` is that cells which
    are empty after stripping become ``pd.NA`` rather than a string of
    15 zeros.  That matters at load time because an all-zero ICN would
    otherwise be treated as a valid join key by every downstream step.

    Parameters:
        s: String series of raw ICN / Xref values.

    Returns:
        A new series where non-empty values are 15-char zero-padded and
        blank / whitespace-only cells are ``NA``.
    """
    stripped: pd.Series = s.str.strip()
    stripped = stripped.mask(stripped.eq(""), pd.NA)
    return stripped.str.zfill(15)


def npi_key_series(s: pd.Series) -> pd.Series:
    """Vectorised :func:`npi_key`: strip; ``NA`` becomes ``""``.

    Mirrors the scalar :func:`npi_key` semantics so call sites can drop
    ``.map(npi_key)`` in favour of a single pandas-native operation.

    Parameters:
        s: Raw NPI series (any dtype; coerced via ``astype("string")``).

    Returns:
        A ``StringDtype`` series with every cell stripped and missing
        values replaced with the empty string.
    """
    return s.astype("string").str.strip().fillna("")


def rx_key_series(s: pd.Series) -> pd.Series:
    """Vectorised :func:`rx_key`: numeric -> 12-char zfill; else stripped.

    Matches the scalar :func:`rx_key` bit-for-bit:

    - Numeric-looking cells (including Excel's ``50037125.0`` floats) are
      rounded through ``Int64`` and left-padded to 12 chars.
    - Non-numeric cells (e.g. letter-containing Rx IDs) pass through as
      the stripped string form.
    - ``NA`` cells become ``""``.

    Parameters:
        s: Raw Rx series (any dtype; coerced via ``astype("string")``).

    Returns:
        A ``StringDtype`` series aligned with *s*.
    """
    stripped: pd.Series = s.astype("string").str.strip()
    # ``errors="coerce"`` turns letter-containing Rx IDs into NA so we
    # can fall back to the stripped string form via ``.where`` below.
    numeric: pd.Series = pd.to_numeric(stripped, errors="coerce").round()
    padded: pd.Series = numeric.astype("Int64").astype("string").str.zfill(12)
    return padded.where(numeric.notna(), stripped).fillna("")


def fill_key(value: object) -> int | None:
    """Parse a Fill Number cell to a plain int; ``None`` when unparseable.

    Parameters:
        value: Raw cell content.  Floats are rounded; strings are
               coerced through ``float``.

    Returns:
        The integer fill number, or ``None`` for missing / non-numeric
        cells.  ``None`` propagates through join-key tuples so such rows
        cannot accidentally match anything.
    """
    if pd.isna(value):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def fill_key_series(s: pd.Series) -> pd.Series:
    """Vectorised :func:`fill_key`: parse to rounded ``Int64``; ``NA`` on failure.

    Returns a nullable-integer series rather than a Python ``None``
    sentinel so downstream masks can use ``.notna()`` directly — the
    same predicate every existing call site already combines with the
    NPI/Rx emptiness checks.

    Parameters:
        s: Raw Fill series (any dtype; strings and floats both work).

    Returns:
        An ``Int64`` series of rounded fill numbers, with ``pd.NA`` for
        cells that were missing or non-numeric.
    """
    return pd.to_numeric(s, errors="coerce").round().astype("Int64")
