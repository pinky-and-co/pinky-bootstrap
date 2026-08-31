#!/usr/bin/env python3
"""Distribute hooks + generate AGENTS.md/CLAUDE.md into the workspace's repos.

Usage (prefer the `pinky` entry point; this shim stays for a bare clone):
    python -m setup.cli --repo pinky-core       # distribute to one repo
    python -m setup.cli --all                   # distribute to every discovered repo
    python -m setup.cli --check-drift           # report repo vs source drift

Implementation lives in the setup/ package (precommit, cli — see the split-setup-py-package
kanban card); this file is a thin entrypoint only.
"""

from setup.cli import main

if __name__ == "__main__":
    main()
