"""Allow `python -m beacon` with the same CLI as the `beacon` console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    main()
