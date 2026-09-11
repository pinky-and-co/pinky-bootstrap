"""The socle `.darglint` carries `ignore_raise = exc` — a linter limitation, not a policy relaxation.

`_write_darglint_config` converges (ADR of 2026-08-07): a repo's own `.darglint` is overwritten, on
the finding that the four existing ones were divergence by accident rather than decisions anyone
held. Correct — but it left no way for a repo to keep a setting it genuinely needs, while the
function's own docstring promised one ("a repo that ever needs its own strictness will say so through
the profile"). That mechanism does not exist.

`pinky-connect` was the casualty, measured 2026-08-07: distributing the socle removed
`ignore_raise = exc` from its `.darglint`, and darglint immediately flagged
`src/pinky_connect/http.py:concurrent_map:225: DAR401: -r exc`.

**That flag is a false positive.** `concurrent_map`'s docstring DOES document `Raises: Exception:`.
darglint reports it because the code does `raise exc` — a *variable* whose type it cannot resolve —
not because anything is undocumented. So the setting suppresses a limitation of the tool, never a
missing docstring, which is exactly why it belongs to the socle rather than to one repo: it is
inert on any repo that does not `raise <variable>`, and it removes the trap for every repo at once.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup


def test_socle_darglint_is_pinned_whole():
    """Whole-output oracle (tests.md § generator oracle). A fragment assertion on `ignore_raise`
    alone would pass just as happily on a file that had lost `strictness = long` — the setting this
    socle exists to converge in the first place."""
    assert setup.precommit._DARGLINT_INI == (
        "[darglint]\n"
        "docstring_style = google\n"
        "strictness = long\n"
        "ignore = DAR402\n"
        "ignore_raise = exc\n"
    )


def test_convergence_rewrites_a_repo_that_lost_the_line(tmp_path):
    """The regression that motivated this: a repo carrying the pre-socle file must be converged
    back UP to the socle, not left behind. `.darglint` is not part of `check_drift`'s comparison
    set, so a stale one is invisible — only the rewrite catches it."""
    repo = tmp_path / "pinky-thing"
    (repo / "src").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (repo / ".darglint").write_text(
        "[darglint]\ndocstring_style = google\nstrictness = long\nignore = DAR402\n",
        encoding="utf-8",
    )

    setup._write_darglint_config(repo, setup.resolve_extras(repo))

    assert (repo / ".darglint").read_text(
        encoding="utf-8"
    ) == setup.precommit._DARGLINT_INI


def test_a_repo_without_the_python_extra_gets_no_darglint(tmp_path):
    """darglint ships with the python extra only — a JS or asset repo must not acquire a config
    for a linter it never runs."""
    repo = tmp_path / "pinky-assets-like"
    repo.mkdir()

    setup._write_darglint_config(repo, setup.resolve_extras(repo))

    assert not (repo / ".darglint").exists()
