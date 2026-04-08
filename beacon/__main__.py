"""Allow `python -m beacon` with the same CLI as the `beacon` console script."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__:
    from .cli import main
else:
    # Running as `python beacon/__main__.py` — __package__ is unset
    _root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(_root))
    from beacon.cli import main

if __name__ == "__main__":
    main()
