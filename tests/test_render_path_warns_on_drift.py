"""The RENDER path must report drift too — the angle ADR-0055 left open.

Card `render-path-ne-verifie-aucune-derive`: ADR-0055 folded the drift check into `run_distribution()`
precisely so nobody could forget it ("the tool tells you, you don't have to think about it"). But it
only fires on the DISTRIBUTION flags (`--repo`, `--all`, `--check-drift`). The second path — rendering,
`--provider claude` / `--profile <name>` / `--into` — writes CLAUDE.md and `.claude/` and checks
nothing. A session that edits `core/pre-commit/` then runs only `--provider claude`, which is what
`feedback_core_edit_needs_setup` prescribes to the letter, walks away believing it distributed while
the 19 repos stay stale without a word. Measured 2026-08-05: 30 divergences accumulated that way.

**Non-blocking, by requirement.** The render path must stay usable on a machine whose repos are not
cloned yet (framework targets #2 and #3 — the brother's POC-light box, a colleague's BYO-profile
setup). Failing there would be worse than saying nothing.

**Wired last, on purpose.** Steps 1-3 of this session had to land first: on a parc where no invocation
could report 0 (10 divergences with no `--profile`, 18 with one), this warning would have fired on
every single render — manufacturing exactly the guard-rail-one-learns-to-ignore that the card is about.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


def _drifted_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "pinky-stale"
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)
    (repo / "scripts" / "hooks" / "commit-msg").unlink()  # core moved on, repo did not
    return repo


# ── warn_on_drift — the notice itself ────────────────────────────────────────


def test_warns_and_names_the_command_that_fixes_it(tmp_path, monkeypatch, capsys):
    """One line, and it has to say what to run next — a warning that only states a number makes the
    reader go looking for the command, which is how a notice becomes noise."""
    repo = _drifted_repo(tmp_path)
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [repo])

    setup.warn_on_drift()

    out = capsys.readouterr().out
    assert "pinky-stale" in out
    assert "pinky drift" in out
    assert "pinky distribute --repo" in out


def test_says_nothing_when_the_parc_is_clean(tmp_path, monkeypatch, capsys):
    """The whole point of ordering this after the per-repo profile fix: on a converged parc the
    render path stays silent. A notice that fires every time is one nobody reads."""
    repo = tmp_path / "pinky-clean"
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [repo])

    capsys.readouterr()  # drain distribute()'s own output — only the notice below counts
    setup.warn_on_drift()
    assert capsys.readouterr().out == ""


def test_is_silent_when_no_repo_is_cloned(monkeypatch, capsys):
    """Framework targets #2/#3 render the config on a machine that has no pinky repo at all. The
    notice must not appear, and must not fail."""
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [])
    setup.warn_on_drift()
    assert capsys.readouterr().out == ""


def test_never_raises_when_the_check_itself_breaks(monkeypatch, capsys):
    """Non-blocking means non-blocking: a render must never be lost to a failure in an advisory
    check. Proven by mutation — the comparison is made to explode."""

    def _boom():
        raise OSError("unreadable workspace")

    monkeypatch.setattr(setup.precommit, "discover_repos", _boom)
    setup.warn_on_drift()  # must return normally


def test_does_not_exit_the_process(tmp_path, monkeypatch):
    """`check_drift` is reached through `run_distribution`, which turns a non-zero count into
    `sys.exit(1)`. The advisory path must not inherit that."""
    repo = _drifted_repo(tmp_path)
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [repo])
    setup.warn_on_drift()  # a SystemExit here fails the test


# ── wiring — both render entry points call it ────────────────────────────────


# `install_from_profile`/`install_into_repo` (the render path this section wired warn_on_drift
# into) were removed 2026-08-17 along with the dead CLAUDE.md render engine — the wiring tests for
# that path went with them. `warn_on_drift()` itself, and its distribution-path wiring, are
# unaffected — see the tests above.
