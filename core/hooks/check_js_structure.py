#!/usr/bin/env python3
"""[JS-STRUCT] Warn when app.js is large but no engine/core sibling holds the logic (warn-only).

The convention (AGENT_JS_CONVENTIONS.md § JS file responsibilities): app.js orchestrates UI
binding, engine.js / core.js holds pure business logic, state.js holds the store. A big app.js
with no engine.js / core.js next to it is the signal that logic was never extracted.
Warn-only (exit 0) — never blocks.
"""

import os
import sys
from pathlib import Path

# Windows' default console codepage (cp1252, not UTF-8) can't encode this hook's ✓/⚠ output and
# crashes with UnicodeEncodeError (found by the windows-latest CI job, CHANTIER0001
# portage-windows-du-moteur). Same fix as setup/__init__.py, applied here because this script runs
# standalone (invoked directly by pre-commit) and never imports that package.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

APP_MAX_LINES = 200
LOGIC_SIBLINGS = ("engine.js", "core.js")


def _line_count(filepath: str) -> int:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _is_disabled() -> bool:
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    if _is_disabled():
        return 0
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
        print(
            f"⚠️  [JS-STRUCT] {filepath}: large app.js with no engine.js/core.js next to it"
        )
        print(
            "   💡 Extract business logic into engine.js — see AGENT_JS_CONVENTIONS.md"
        )
    return 0  # warn-only


if __name__ == "__main__":
    sys.exit(main())
