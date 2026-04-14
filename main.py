"""IDE entry point — equivalent to `python -m beacon`."""

import runpy

runpy.run_module("beacon", run_name="__main__", alter_sys=True)
