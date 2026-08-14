"""Drift must look BOTH ways — `extra hook …`, the missing half of `missing hook …`.

Card `defauts-moteur-releves-a-l-import-pluto` § 3: `distribute()` writes the hooks a profile keeps
but never removes the ones it drops. Applying `--profile pluto-poc` removed `check-forbidden-keywords`
and `check-zws` from `.pre-commit-config.yaml` while leaving `check_forbidden_keywords.py` and
`check_zws.py` on disk, orphaned and wired to nothing. Re-observed 2026-08-06 on 4 repos: still there
ten weeks later, referenced 0 times.

They stayed invisible because `check_drift` only ever iterated the EXPECTED set — it could report a
file that should be there and isn't, never one that is there and shouldn't be. The 4 repos came out
`✓` with an orphan each.

**Signal only, no deletion** (the card's least-invasive option): removing a file from a consumer repo
is not a neutral act, and the report is what makes the stock visible in the first place.
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


def _distributed_repo(tmp_path: Path, name: str = "pinky-thing") -> Path:
    repo = tmp_path / name
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)
    return repo


def test_an_orphan_framework_script_is_reported(tmp_path, capsys):
    """The exact 2026-07-31 shape: the profile drops a hook, the script stays behind.

    `check_forbidden_keywords` is the whole of `HOOK_MANIFEST` today (`check_zws` moved to the
    always-on socle, ADR-0062), so an empty selection is what "the profile drops it" means — and it
    is the very script the 4 pluto repos carried orphaned.
    """
    repo = _distributed_repo(tmp_path)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=set())
    assert (repo / "scripts" / "hooks" / "check_forbidden_keywords.py").exists(), (
        "precondition: distribute() still leaves the deselected script behind"
    )

    total = setup.check_drift([repo], set())

    out = capsys.readouterr().out
    assert "extra hook scripts/hooks/check_forbidden_keywords.py" in out
    assert total > 0


def test_a_clean_repo_reports_no_extra(tmp_path, capsys):
    """The files distribute() writes outside the hook catalogue — docs_identity.json, badges.toml —
    are legitimate and must never be flagged. Without this the check would fire on every repo."""
    repo = _distributed_repo(tmp_path)
    assert setup.check_drift([repo]) == 0
    assert "extra hook" not in capsys.readouterr().out


def test_a_script_the_repo_owns_is_not_flagged(tmp_path, capsys):
    """The signal is scoped to files the FRAMEWORK ships. A repo dropping its own helper in
    scripts/hooks/ is doing nothing wrong, and a drift check that nags about it is one people
    learn to ignore — the failure mode this whole card is about."""
    repo = _distributed_repo(tmp_path)
    (repo / "scripts" / "hooks" / "our_own_helper.py").write_text(
        "# ours\n", encoding="utf-8"
    )

    assert setup.check_drift([repo]) == 0
    assert "our_own_helper" not in capsys.readouterr().out


def test_an_orphan_alone_does_not_fail_the_post_distribution_gate(
    tmp_path, monkeypatch, capsys
):
    """`distribute()` writes but never deletes, so it CANNOT clear an orphan. If the residual gate
    counted them, `--repo <name>` would exit non-zero forever on any repo carrying one — a control
    that fails on the nominal path and cannot be satisfied by the tool it gates. That is the exact
    failure the archived card `drift-check-faux-positif-sans-manifeste` was opened for; re-creating
    it while fixing its sibling would be a poor trade.

    The orphan is still REPORTED — signal preserved, gate honest.
    """
    import argparse

    repo = _distributed_repo(tmp_path, "pinky-orphaned")
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=set())
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [repo])
    monkeypatch.setattr(setup.precommit, "_load_docs_identity", lambda _p: IDENTITY)
    monkeypatch.setattr(setup.precommit, "profile_selected_hooks", lambda _p: set())
    monkeypatch.setattr(
        setup.precommit, "load_profile", lambda _n: ({"name": "lean"}, None)
    )
    monkeypatch.setattr(setup.precommit, "profile_hooks_enabled", lambda _p: True)
    # External CLIs (prek, detect-secrets) are a boundary, not the subject: absent from PATH they
    # populate _MISSING_TOOLS and run_distribution exits 1 for a reason unrelated to this test.
    # They are on the author's PATH and not on the CI runner's — a THIRD ambient axis beyond the two
    # conftest.py names, and the one that turned this test red on CI while green locally.
    monkeypatch.setattr(setup.precommit, "_prek_install", lambda *_a, **_k: None)
    monkeypatch.setattr(
        setup.precommit, "_ensure_secrets_baseline", lambda *_a, **_k: None
    )

    args = argparse.Namespace(
        profile="lean",
        repo="pinky-orphaned",
        all=False,
        dry_run=False,
        check_drift=False,
        commit=False,
        force=False,
    )
    setup.run_distribution(args)  # a SystemExit here is the regression

    assert (
        "extra hook scripts/hooks/check_forbidden_keywords.py"
        in capsys.readouterr().out
    )


def test_extra_and_missing_are_counted_together(tmp_path, capsys):
    """Both directions land in the same divergence total, so a parc with only orphans still exits
    non-zero — an integrity control that reports a problem but returns 0 is decorative."""
    repo = _distributed_repo(tmp_path)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=set())
    (
        repo / "scripts" / "hooks" / "commit-msg"
    ).unlink()  # socle hook, expected but absent

    total = setup.check_drift([repo], set())

    out = capsys.readouterr().out
    assert "missing hook scripts/hooks/commit-msg" in out
    assert "extra hook scripts/hooks/check_forbidden_keywords.py" in out
    assert total >= 2
