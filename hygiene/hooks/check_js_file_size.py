#!/usr/bin/env python3
"""[JS-SIZE] Warn when a .js file grows past the size threshold (warn-only, never blocks).

A large .js file usually means orchestration and business logic live in the same place — the
fix is structural (extract the logic), not cosmetic. This hook only warns (exit 0) so it never
blocks a commit.
"""

import os
import sys
from pathlib import Path

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
    """Warn on every `.js` argument over `JS_MAX_LINES`; always exits 0 (warn-only)."""
    if _is_disabled():
        return 0
    for filepath in sys.argv[1:]:
        if not filepath.endswith(".js") or filepath.endswith(".min.js"):
            continue
        n = _line_count(filepath)
        if n > JS_MAX_LINES:
            print(f"⚠️  [JS-SIZE] {filepath}: {n} lines (> {JS_MAX_LINES})")
            print(
                "   💡 Extract business logic into engine.js — see AGENT_JS_CONVENTIONS.md"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
