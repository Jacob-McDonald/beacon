"""Paths resolved relative to the project root (repository directory)."""

from __future__ import annotations

from pathlib import Path

# beacon/paths.py -> beacon/ -> project root
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
