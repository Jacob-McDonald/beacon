"""Package entry point executed by ``python -m beacon``.

Python looks for a file named exactly ``__main__.py`` inside a package when
the ``-m`` flag is used (e.g. ``python -m beacon``).  A file named ``main.py``
would have no special meaning — it would just be an ordinary module.

Why two entry points?
~~~~~~~~~~~~~~~~~~~~~

There are two ways to launch Beacon, but they share a single implementation
(``beacon.cli.main``), so no logic is duplicated:

1. **``python -m beacon``** — the *developer / source* entry point.  Runs
   directly from a repo checkout with no install step.  Python uses this
   ``__main__.py`` file to bootstrap the package, then delegates to
   ``cli.main()``.

2. **``beacon`` shell command** — the *installed user* entry point.  After
   ``pip install``, a console-script wrapper (declared in ``pyproject.toml``)
   calls ``cli.main()`` directly.  ``__main__.py`` is not involved.

This file exists solely to enable path (1).  It is intentionally thin — a
single import and a single call — so that all argument parsing and
orchestration live in :mod:`beacon.cli` where both paths can reuse them.
"""

from __future__ import annotations

from beacon.cli import main

if __name__ == "__main__":
    main()
