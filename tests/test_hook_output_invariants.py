"""Anti-bloat invariant over harness hooks (incident 2026-07-04).

A hook that persists a MANAGED BLOCK into a file (marked by a `BLOCK_START` constant) must build that
block as a pure function of state — no wall-clock, no nonce. Otherwise the block differs every turn, the
hook rewrites the file, and because that file may already be in the agent's context the harness
re-injects it whole → pure token waste (this is exactly how the auto-handoff timestamp leaked ~1K/turn).

This guard scans every harness hook and fails if a managed-block writer references a wall-clock call.
It is generic: it protects future hooks, not just the one we already fixed.
"""

import re
import sys
from pathlib import Path

HOOKS = Path(__file__).parent.parent / "agentic-harness" / "status-lines"
sys.path.insert(0, str(HOOKS))

_WALLCLOCK = re.compile(
    r"\b(?:datetime\.now|datetime\.utcnow|time\.time|time\.monotonic)\s*\("
)


def test_managed_block_hooks_have_no_wallclock():
    offenders = []
    for f in sorted(HOOKS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        if "BLOCK_START" not in src:
            continue  # not a managed-block writer → the invariant does not apply
        if _WALLCLOCK.search(src):
            offenders.append(f.name)
    assert not offenders, (
        "managed-block hooks must build their block from state only (no wall-clock) or they churn the "
        f"file and force context re-injection: {offenders}"
    )


def test_statusline_is_total_and_never_raises():
    # The statusline must render on a bare/garbage payload — an error blanks the whole bar.
    # build_lines() covers the missing-field floor; main()'s own try/except (exercised via
    # subprocess in tests/test_statusline.py) covers type-poisoned fields on top of that.
    import statusline as sl

    lines = sl.build_lines({})
    assert lines and lines[0].strip()  # missing everything → still a non-empty skeleton
    assert sl._count_subagents("/nope/nope.jsonl", "sess") in (
        None,
        0,
    )  # unreadable transcript → degrades, no crash
