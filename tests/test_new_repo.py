"""`setup.py --new-repo <name>` — a new repo is born already governed (chantier-0001 card
repo-bootstrap-from-zero). Scope decision (2026-07-11): repo nu + distribute(), no product
scaffolding — git init + `develop` branch, then the existing distribution path (which writes
.pre-commit-config.yaml / hooks / prek install). Idempotent: re-running converges, never re-inits.

The git-skeleton is tested here in isolation (tmp_path); the distribution it delegates to
(run_distribution) is already covered elsewhere and must NOT run against the real WORKSPACE_ROOT.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup


def _current_branch(repo: Path) -> str:
    return subprocess.run(
        ["git", "symbolic-ref", "--short", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


# ── _init_repo_skeleton — git init + unborn develop branch ────────────────────


def test_init_repo_skeleton_creates_develop_branch(tmp_path):
    target = tmp_path / "pinky-foo"
    created = setup._init_repo_skeleton(target)
    assert created is True
    assert (target / ".git").exists()
    assert _current_branch(target) == "develop"


def test_init_repo_skeleton_idempotent(tmp_path):
    target = tmp_path / "pinky-foo"
    assert setup._init_repo_skeleton(target) is True
    # Second call on an existing git repo: no re-init, returns False, never raises.
    assert setup._init_repo_skeleton(target) is False
    assert _current_branch(target) == "develop"


# ── distribute() → check_drift() must be stable on a bare new repo ────────────


def test_bare_repo_has_no_drift_right_after_distribution(tmp_path):
    """Regression for the card `drift-check-faux-positif-sans-manifeste`: `--new-repo` (no
    `--scaffold`) always reported `missing hook scripts/hooks/check_weak_assertions.py` right after
    a clean distribution. Root cause was `resolve_extras()` re-scanning `*.py` on the SECOND call
    (inside `check_drift`) and finding the socle scripts `distribute()` had just copied into
    `scripts/hooks/` — a self-inflicted flip from `[]` to `['python-lint']`. Fixed by excluding
    `scripts/hooks/` from that scan (it is 100% framework-owned, see `resolve_extras`'s docstring).
    """
    target = tmp_path / "pinky-bare"
    setup._init_repo_skeleton(target)
    assert setup.resolve_extras(target) == []

    identity = setup.SuiteIdentity(
        header_image_url="https://example.test/header.png",
        header_alt="pinky",
        suite_line="Part of the pinky suite.",
        github_org="pinky-test",
        pitch_heading="Why x",
        pitch_paragraphs=("x",),
        pitch_pills=("x",),
    )
    setup.distribute(target, dry_run=False, identity=identity)

    # The bug: distribute()'s own output poisoned the NEXT resolve_extras() call.
    assert setup.resolve_extras(target) == []
    assert setup.check_drift([target], None) == 0
