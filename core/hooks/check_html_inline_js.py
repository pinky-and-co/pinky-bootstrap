#!/usr/bin/env python3
"""[HTML-JS] Warn on inline <script> blocks with a body in an .html file (warn-only).

Inline JS bypasses the file-responsibility split (app.js / engine.js / state.js) and cannot be
minified/cached. External <script src="..."> and structured-data blocks (JSON-LD / application/json,
used for SEO/GEO schema markup) are NOT flagged — only real inline JS bodies. Warn-only (exit 0).
"""

import os
import re
import sys
from pathlib import Path

# Windows' default console codepage (cp1252, not UTF-8) can't encode this hook's ✓/⚠ output and
# crashes with UnicodeEncodeError (found by the windows-latest CI job, CHANTIER0001
# portage-windows-du-moteur). Same fix as setup/__init__.py, applied here because this script runs
# standalone (invoked directly by pre-commit) and never imports that package.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# <script ...> ... </script> with a captured body; case-insensitive, across newlines.
SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
SRC_RE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
DATA_TYPE_RE = re.compile(
    r"""type\s*=\s*["']application/(ld\+json|json)["']""", re.IGNORECASE
)


def _inline_script_count(filepath: str) -> int:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return 0
    count = 0
    for attrs, body in SCRIPT_RE.findall(text):
        if SRC_RE.search(attrs) or DATA_TYPE_RE.search(attrs):
            continue  # external script or structured-data block — not inline JS
        if body.strip():
            count += 1
    return count


def _is_disabled() -> bool:
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    if _is_disabled():
        return 0
    for filepath in sys.argv[1:]:
        if not filepath.endswith(".html"):
            continue
        n = _inline_script_count(filepath)
        if n:
            print(f"⚠️  [HTML-JS] {filepath}: {n} inline <script> block(s) with a body")
            print("   💡 Move JS to a .js file — see AGENT_JS_CONVENTIONS.md")
    return 0  # warn-only


if __name__ == "__main__":
    sys.exit(main())
