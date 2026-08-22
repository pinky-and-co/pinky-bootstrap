#!/usr/bin/env python3
"""Thin entrypoint for the `pinky` toolbox — the implementation lives in `setup/cli_pinky.py`.

Kept as a root-level file, not folded into `setup/`, because two entry points are legitimate: the
installed console script (`pinky …`, `[project.scripts]` in pyproject.toml) and a direct run before
any install (`python cli_pinky.py …`, from a bare git clone). The substance moved to `setup/` so an
editable install (`packages = ["setup"]`) picks up edits live — this file previously went through
`force-include` instead, which froze a stale copy in site-packages (kanban card
`cli-pinky-py-n-est-pas-editable`). Same pattern as `setup.py` at this same root: a permanent, rarely
touched shim, never the place logic accumulates.

Usage:
    python cli_pinky.py new-repo pluto-poc-x --scaffold --type web
    python cli_pinky.py distribute --repo pinky-core
    python cli_pinky.py rules
    python cli_pinky.py drift
    python cli_pinky.py check-public
"""

import sys

from setup.cli_pinky import main, setup_main  # noqa: F401 — re-exported for direct-run + tests

if __name__ == "__main__":
    sys.exit(main() or 0)
