#!/usr/bin/env python3
"""[JS-SIZE] Block when a .js file grows past the size threshold.

A large .js file usually means orchestration and business logic live in the same place — the
fix is structural (extract the logic), not cosmetic. The hook blocks (exit 1), so the
agent that grew the file sees it and splits it.
"""

import os
import sys
from pathlib import Path

from _report import Diagnostic, emit

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

JS_MAX_LINES = 200


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
    """Fail on every `.js` argument over `JS_MAX_LINES`."""
    if _is_disabled():
        return 0
    findings = [
        Diagnostic(
            "JS-SIZE",
            f"{n} lines (> {JS_MAX_LINES})",
            filepath,
            help="extract business logic into engine.js — see pc-craft:code-conventions",
        )
        for filepath in sys.argv[1:]
        if filepath.endswith(".js") and not filepath.endswith(".min.js")
        if (n := _line_count(filepath)) > JS_MAX_LINES
    ]
    emit(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
