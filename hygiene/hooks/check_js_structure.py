#!/usr/bin/env python3
"""[JS-STRUCT] Warn when app.js is large but no engine/core sibling holds the logic (warn-only).

The convention: app.js orchestrates UI binding, engine.js / core.js holds pure business logic,
state.js holds the store. A big app.js with no engine.js / core.js next to it is the signal that
logic was never extracted. Warn-only (exit 0) — never blocks.
"""

import os
import sys
from pathlib import Path

from _report import Diagnostic, emit

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

APP_MAX_LINES = 200
LOGIC_SIBLINGS = ("engine.js", "core.js")


def _line_count(filepath: str) -> int:
    """Number of lines in `filepath`, or 0 if it can't be opened."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Warn on every `app.js` over `APP_MAX_LINES` with no `LOGIC_SIBLINGS` beside it; always exits 0."""
    if _is_disabled():
        return 0
    findings: list[Diagnostic] = []
    for filepath in sys.argv[1:]:
        if os.path.basename(filepath) != "app.js":
            continue
        if _line_count(filepath) <= APP_MAX_LINES:
            continue
        folder = os.path.dirname(filepath)
        if any(
            os.path.exists(os.path.join(folder, sibling)) for sibling in LOGIC_SIBLINGS
        ):
            continue
        findings.append(
            Diagnostic(
                "JS-STRUCT",
                "large app.js with no engine.js/core.js next to it",
                filepath,
                help="extract business logic into engine.js — see pc-craft:code-conventions",
                severity="warning",
            )
        )
    emit(findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
