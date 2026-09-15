#!/usr/bin/env python3
"""Thin entrypoint for the `pinky` toolbox — the implementation lives in `setup/cli_pinky.py`.

Two entry points are legitimate: the installed console script (`pinky …`, `[project.scripts]` in
pyproject.toml) and a direct run before any install (`python cli_pinky.py …`, from a bare git
clone). The substance lives in `setup/` so an editable install (`packages = ["setup"]`) picks up
edits live; distributing this file itself via `force-include` would freeze a stale copy in
site-packages, out of sync with those edits.

Usage:
    python cli_pinky.py new-repo pluto-poc-x --scaffold --type web
    python cli_pinky.py distribute --repo pinky-core
    python cli_pinky.py install
    python cli_pinky.py rules
    python cli_pinky.py drift
    python cli_pinky.py check-public
"""

import sys

from setup.cli_pinky import (  # noqa: F401 — re-exported for direct-run + tests
    main,
    setup_main,
)

if __name__ == "__main__":
    main()
    sys.exit(0)
