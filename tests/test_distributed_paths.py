"""`--commit` must stage every file the distribution writes — `.darglint` included.

`commit_distribution` stages exactly `DISTRIBUTED_PATHS`. `.darglint` was missing from that tuple
even though `_write_darglint_config` rewrites it on every distribution to a python-extra repo. So
with ONLY `.darglint` changed, `setup.py --repo <name> --commit` returned
**"up-to-date (nothing to commit)"** — measured, not assumed — while the file sat modified in the
working tree. Not an incomplete commit: a clean bill of health over a change it never looked at.

Found 2026-08-07 while adding `ignore_raise = exc` to the socle — the 9 python repos each came out
with a modified `.darglint` that had to be committed by hand.

**`.secrets.baseline` is deliberately NOT in the set**, and not because a human edits it — checked
across the parc, none ever has. It is created once when missing, then rewritten by detect-secrets in
reaction to the repo's OWN code (`pinky-provider` 3b3547a filled its `results` with findings from a
`secret.py` that same commit added). A distribution therefore never modifies it, so staging it could
only sweep a repo-side change into a distribution commit.
"""

import subprocess
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _python_repo_with_a_baseline_commit(tmp_path: Path, monkeypatch) -> Path:
    """A python-extra repo whose distributed files are already committed once.

    `prek` and `detect-secrets` are stubbed out: `commit_distribution` deliberately runs hooks (no
    `--no-verify`), so with prek on PATH the outcome would depend on whether the fixture satisfies
    every hook, and without it (the CI runner) on nothing at all. Same third ambient axis as
    `conftest.py` § 3 — the subject here is which paths get staged, not the hook wall.
    """
    monkeypatch.setattr(setup.precommit, "_prek_install", lambda *_a, **_k: None)
    monkeypatch.setattr(
        setup.precommit, "_ensure_secrets_baseline", lambda *_a, **_k: None
    )
    repo = tmp_path / "pinky-thing"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'thing'\nversion = '0'\n", encoding="utf-8"
    )
    setup._init_repo_skeleton(repo)
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "test")
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "🎉 feat: initial commit", "--no-verify")
    return repo


def test_commit_distribution_stages_a_changed_darglint(tmp_path, monkeypatch):
    """The regression: with only `.darglint` changed, `--commit` left it behind and announced
    "up-to-date (nothing to commit)"."""
    repo = _python_repo_with_a_baseline_commit(tmp_path, monkeypatch)
    assert setup.resolve_extras(repo) == ["python"]

    # The repo must COMMIT a stale .darglint first — otherwise converging it back to the socle
    # produces no diff and the test asserts nothing (the shape this test failed in on first run).
    (repo / ".darglint").write_text(
        "[darglint]\nstrictness = short\n", encoding="utf-8"
    )
    _git(repo, "add", ".darglint")
    _git(repo, "commit", "-m", "🔧 chore: stale darglint", "--no-verify")

    setup._write_darglint_config(repo, setup.resolve_extras(repo))
    assert "M" in _git(repo, "status", "--porcelain", ".darglint")

    status = setup.commit_distribution(repo)

    assert status == "committed", status
    assert ".darglint" in _git(repo, "show", "--name-only", "--format=", "HEAD")
    assert _git(repo, "status", "--porcelain") == ""


def test_secrets_baseline_is_not_a_distributed_path():
    """A distribution never writes this file after seeding it, so staging it could only ever carry
    a repo-side change into a distribution commit.

    Asserted on the tuple rather than through a real commit, on purpose. Driving it behaviourally
    means writing a `.secrets.baseline` and committing for real — which runs the `Detect secrets`
    hook, so the test would pass or fail on whether the fixture's JSON satisfies detect-secrets and
    on whether `prek` is on PATH (absent from the CI runner — the ambient axis that already turned
    two tests red on 2026-08-07). The staging mechanism itself is covered behaviourally by
    `test_commit_distribution_stages_a_changed_darglint`; what is left to pin here is the membership
    decision, and that is exactly what this asserts.
    """
    assert ".secrets.baseline" not in setup.DISTRIBUTED_PATHS


def test_distributed_paths_is_pinned_whole():
    """Whole-tuple oracle: a fragment assertion on `.darglint` alone would still pass if a later
    edit dropped `.gitleaks.toml` or a workflow — each of which would silently un-stage a file every
    distribution writes, the very class of bug this module exists for."""
    assert setup.DISTRIBUTED_PATHS == (
        ".pre-commit-config.yaml",
        ".gitleaks.toml",
        ".gitattributes",
        ".darglint",
        "scripts/hooks",
        ".github/workflows/ci.yml",
        ".github/workflows/prek.yml",
    )
