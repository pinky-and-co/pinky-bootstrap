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

from _report import Diagnostic, emit

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
SRC_RE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
DATA_TYPE_RE = re.compile(
    r"""type\s*=\s*["']application/(ld\+json|json)["']""", re.IGNORECASE
)


def _inline_script_count(filepath: str) -> int:
    """Count of `<script>` blocks in `filepath` with a non-empty body and no `src`/JSON-LD type."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return 0
    count = 0
    for attrs, body in SCRIPT_RE.findall(text):
        if SRC_RE.search(attrs) or DATA_TYPE_RE.search(attrs):
            continue
        if body.strip():
            count += 1
    return count


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def main() -> int:
    """Warn on every `.html` argument that has an inline `<script>` body; always exits 0."""
    if _is_disabled():
        return 0
    findings = [
        Diagnostic(
            "HTML-JS",
            f"{n} inline <script> block(s) with a body",
            filepath,
            help="move JS to a .js file — see pc-craft:code-conventions",
            severity="warning",
        )
        for filepath in sys.argv[1:]
        if filepath.endswith(".html")
        if (n := _inline_script_count(filepath))
    ]
    emit(findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
