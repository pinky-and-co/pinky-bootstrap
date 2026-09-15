#!/usr/bin/env python3
"""[JS-ENGINE-SYNC] Block when engine.js is staged but its engine.min.js is not (hard block).

The CDN serves the minified file only — the source must not be reachable. Committing engine.js
without regenerating engine.min.js ships stale behaviour.
This is the ONLY web hook that is a hard block (exit 1) — on every repo, POC included.

The staged set is read from `git diff --cached --name-only`, NOT from argv: `prek` (unlike
classic pre-commit) can split matched files across several separate invocations of the same
hook, so a source and its sibling can each land in a different batch and never see each other
via sys.argv. Git's own staged-file list is invocation-independent and always complete.
"""

import os
import subprocess
import sys
from pathlib import Path

# Script autonome, n'importe pas `setup` : la console Windows (cp1252) ne sait pas encoder ✓/⚠.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def _is_disabled() -> bool:
    """True if this hook's filename stem is listed in `PINKY_DISABLED_HOOKS` (comma-separated)."""
    disabled = os.environ.get("PINKY_DISABLED_HOOKS", "")
    return Path(__file__).stem in {h.strip() for h in disabled.split(",") if h.strip()}


def _min_sibling(js_path: str) -> str:
    """foo/engine.js → foo/engine.min.js."""
    return js_path[: -len(".js")] + ".min.js"


def _staged_files() -> set[str]:
    """Paths currently staged for commit (added/copied/modified), per `git diff --cached`."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    return set(result.stdout.splitlines())


def main() -> int:
    """Fail if a staged `engine.js` has no matching staged `engine.min.js`; returns 1 on any mismatch."""
    if _is_disabled():
        return 0
    staged = _staged_files()
    failed = False
    for filepath in sorted(f for f in sys.argv[1:] if f in staged):
        if not filepath.endswith("engine.js") or filepath.endswith(".min.js"):
            continue
        expected = _min_sibling(filepath)
        if expected not in staged:
            print(f"❌ [JS-ENGINE-SYNC] {filepath} staged but {expected} not updated.")
            print(
                f"   💡 Fix: npx terser {filepath} -o {expected} -c -m && git add {expected}"
            )
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
