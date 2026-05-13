"""Helpers shared across the report submodules."""

from __future__ import annotations

from beacon.constants import NPI_TO_SHEET


def location_name(npi: str) -> str:
    """Short pharmacy label for display; falls back to the raw NPI.

    Maps an NPI to its MTF sheet name (e.g. ``"MTF - Hayden"``) then
    strips the ``"MTF - "`` prefix so reports read naturally
    (``"Hayden"`` instead of ``"MTF - Hayden"``).
    """
    return NPI_TO_SHEET.get(npi, npi).removeprefix("MTF - ")
