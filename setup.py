#!/usr/bin/env python3
"""Distribute hooks + generate AGENTS.md/CLAUDE.md into the workspace's repos.

Usage (from workspace root):
    python pinky-workspace/setup.py --repo pinky-core       # distribute to one repo
    python pinky-workspace/setup.py --all                   # distribute to every discovered repo
    python pinky-workspace/setup.py --check-drift            # report repo vs source drift

Implementation lives in the setup/ package (precommit, cli — see the split-setup-py-package
kanban card); this file is a thin entrypoint only.
"""

from setup.cli import main

if __name__ == "__main__":
    main()
