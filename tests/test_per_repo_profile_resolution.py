"""`--all` and `--check-drift` resolve the profile PER REPO instead of imposing the caller's.

The measured defects this closes (cards `render-path-ne-verifie-aucune-derive` points 2-3 and
`defauts-moteur-releves-a-l-import-pluto` § 4):

- `setup.py --all` applied one profile to the whole parc. On 2026-07-31 it silently reverted
  `pluto-poc-pilot` to the full socle — employer-keyword scanner and pinky identity reinstalled —
  then printed `✓` and `No drift`, because "no drift" was computed against the profile just applied.
- `--check-drift` compared every repo to whichever profile the caller passed. Measured 2026-08-07 on
  the 19-repo parc: 10 divergences with no `--profile`, 18 with `--profile pluto`. No invocation
  reported 0, so the only integrity control of the parc was permanently red.

Both read the memory laid down by `distribute()` (see `test_repo_profile_memory.py`).

**Degradation is part of the contract, not an edge case.** Resolving a recorded profile parses YAML,
and the no-profile distribution path is required to run without pyyaml (`test_no_hard_yaml_dependency`
— the Windows CI job installs none). A repo may also record a profile that no longer exists: `pluto-poc`
was a real profile of this parc and is gone. Neither may abort a parc-wide scan.
"""

import argparse
import json
import sys
from pathlib import Path

import pytest

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


def _corpus_with_profile(root: Path, name: str, hooks: list[str] | None) -> None:
    """A real corpus root holding a real profile — never a stub of load_profile itself.

    The contract under test is "the recorded name resolves to that profile's hook selection", so
    the resolution has to run for real (tests.md § never mock the subject).
    """
    pdir = root / "profiles" / name
    pdir.mkdir(parents=True)
    body = f"name: {name}\nlayers:\n  hooks: true\n"
    if hooks == []:
        # `hooks:` with no items parses as None = "no filter", the opposite of an empty selection.
        # Writing the flow form is what makes the à-la-carte tests below able to fail at all.
        body += "hooks: []\n"
    elif hooks is not None:
        body += "hooks:\n" + "".join(f"  - {h}\n" for h in hooks)
    (pdir / "profile.yaml").write_text(body, encoding="utf-8")
    (pdir / "docs_identity.json").write_text(IDENTITY.to_json(), encoding="utf-8")


def _repo_on_profile(root: Path, name: str, profile: str | None) -> Path:
    repo = root / name
    setup._init_repo_skeleton(repo)
    setup.distribute(
        repo,
        dry_run=False,
        identity=IDENTITY,
        selected_hooks=None,
        profile_name=profile,
    )
    return repo


# ── check_drift resolves each repo's own profile ─────────────────────────────


def test_drift_applies_the_profile_the_repo_records(tmp_path, monkeypatch, capsys):
    """A repo on a filtering profile must not be reported as `missing hook` for a hook that profile
    deliberately drops. That false positive is 4 of the 10 divergences measured on 2026-08-07."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(
        corpus, "lean", hooks=[]
    )  # à-la-carte: drop every selectable hook
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))

    # Distributed ONCE, under the profile it records — the state a real `--repo <name> --profile
    # lean` leaves behind on a fresh repo. Distributing unfiltered first would leave the deselected
    # script orphaned on disk, which `extra hook …` now (correctly) reports: a different defect,
    # covered by test_drift_extra_hooks.py, that would mask what this test is about.
    repo = tmp_path / "pinky-lean"
    setup._init_repo_skeleton(repo)
    profile, _ = setup.load_profile("lean")
    setup.distribute(
        repo,
        dry_run=False,
        identity=IDENTITY,
        selected_hooks=setup.profile_selected_hooks(profile),
        profile_name="lean",
    )

    assert setup.check_drift([repo]) == 0
    assert "✓ pinky-lean" in capsys.readouterr().out


def test_an_explicit_selection_still_wins_over_the_recorded_one(tmp_path, monkeypatch):
    """`--profile X --check-drift` keeps asking "what would this parc look like under X?" — an
    explicit question the caller is entitled to. Only the ABSENT flag delegates to the repo."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "lean", hooks=[])
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))

    repo = _repo_on_profile(tmp_path, "pinky-lean", "lean")  # distributed UNFILTERED
    # Recorded profile says "drop everything" → would be ✓. The explicit empty selection asks the
    # same question, so this pins that the explicit argument is what got used, not the record.
    assert setup.check_drift([repo], set()) > 0


def test_a_repo_with_no_record_is_compared_unfiltered(tmp_path):
    """The whole parc is in this state until it is redistributed once. Behaviour must be exactly
    what it was before the memory existed — otherwise the change breaks every repo at once."""
    repo = _repo_on_profile(tmp_path, "pinky-plain", None)
    assert setup.repo_profile(repo) is None
    assert setup.check_drift([repo]) == 0


def test_without_pyyaml_the_scan_degrades_instead_of_dying(
    tmp_path, monkeypatch, capsys
):
    """The no-profile distribution path must run without pyyaml (`test_no_hard_yaml_dependency` —
    the Windows CI job installs none). Now that EVERY repo records a profile, resolving it would
    otherwise make drift demand pyyaml on every machine. Measured by blocking the import for real,
    not asserted from reading the code: `load_profile` calls `sys.exit`, so an unguarded resolution
    would kill the whole scan rather than degrade one repo.
    """
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "lean", hooks=[])
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))
    repo = _repo_on_profile(tmp_path, "pinky-lean", "lean")

    monkeypatch.delitem(sys.modules, "yaml", raising=False)
    monkeypatch.setattr(
        setup.precommit,
        "load_profile",
        lambda _n: pytest.fail("load_profile must not be reached without pyyaml"),
    )

    class _BlockYaml:
        def find_spec(self, name, path=None, target=None):
            if name == "yaml" or name.startswith("yaml."):
                raise ModuleNotFoundError("pyyaml deliberately unavailable")
            return None

    monkeypatch.setattr(sys, "meta_path", [_BlockYaml(), *sys.meta_path])

    setup.check_drift([repo])  # must not raise, must not SystemExit

    out = capsys.readouterr().out
    assert "pyyaml unavailable" in out and "unfiltered" in out


def test_an_unresolvable_recorded_profile_degrades_and_says_so(
    tmp_path, monkeypatch, capsys
):
    """`pluto-poc` was a real profile of this parc and no longer exists. A repo still recording it
    must be reported as unfiltered WITH a note — never crash the scan, never silently pretend the
    filter was applied (that would hide real drift behind a reassuring ✓)."""
    corpus = tmp_path / "corpus"
    (corpus / "profiles").mkdir(parents=True)
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))

    repo = _repo_on_profile(tmp_path, "pinky-orphan", "profile-that-was-deleted")
    setup.check_drift([repo])

    out = capsys.readouterr().out
    assert "profile-that-was-deleted" in out
    assert "unfiltered" in out


# ── --all no longer imposes the caller's profile ─────────────────────────────


def _args(**over) -> argparse.Namespace:
    base = dict(
        profile=None,
        repo=None,
        all=True,
        dry_run=True,
        check_drift=False,
        commit=False,
        force=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_all_skips_repos_recorded_on_another_profile(tmp_path, monkeypatch, capsys):
    """The 2026-07-31 incident, in one test: `--all` under the default profile must leave a repo
    placed on another regime alone, and name it so the operator knows what to run separately."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "house", hooks=None)
    _corpus_with_profile(corpus, "guest", hooks=None)
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)

    ours = _repo_on_profile(tmp_path, "pinky-ours", "house")
    theirs = _repo_on_profile(tmp_path, "pinky-theirs", "guest")
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [ours, theirs])

    capsys.readouterr()  # drain the fixture's own distribution noise — only the run below counts
    setup.run_distribution(_args(profile="house"))

    out = capsys.readouterr().out
    # `(extras:` is the distribution banner — the line distribute() prints, and only it. Matching on
    # the repo name alone would also match the skip notice, which names the repo on purpose.
    assert "→ pinky-ours  (extras:" in out
    assert "→ pinky-theirs  (extras:" not in out
    assert "SKIPPED" in out and "guest" in out  # and says which regime it is on


def test_force_applies_the_callers_profile_anyway(tmp_path, monkeypatch, capsys):
    """The override has to exist: converging a parc onto one profile on purpose is legitimate. It
    just may not be what an unqualified `--all` does."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "house", hooks=None)
    _corpus_with_profile(corpus, "guest", hooks=None)
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)

    ours = _repo_on_profile(tmp_path, "pinky-ours", "house")
    theirs = _repo_on_profile(tmp_path, "pinky-theirs", "guest")
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [ours, theirs])

    capsys.readouterr()  # drain the fixture's own distribution noise
    setup.run_distribution(_args(profile="house", force=True))

    out = capsys.readouterr().out
    assert "→ pinky-ours  (extras:" in out and "→ pinky-theirs  (extras:" in out
    assert "SKIPPED" not in out


def test_repo_targets_one_repo_by_name_and_is_never_skipped(
    tmp_path, monkeypatch, capsys
):
    """`--repo X --profile Y` names both sides — the intent is explicit, so the guard must not fire.
    It is also the documented recovery gesture for a repo `--all` got wrong; a guard here would
    block the fix along with the mistake."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "house", hooks=None)
    _corpus_with_profile(corpus, "guest", hooks=None)
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)

    theirs = _repo_on_profile(tmp_path, "pinky-theirs", "guest")
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [theirs])

    capsys.readouterr()  # drain the fixture's own distribution noise
    setup.run_distribution(_args(all=False, repo="pinky-theirs", profile="house"))
    out = capsys.readouterr().out
    assert "→ pinky-theirs  (extras:" in out and "SKIPPED" not in out


def test_distribution_records_the_profile_it_applied(tmp_path, monkeypatch):
    """End to end: after a real (non-dry-run) `--repo`, the repo knows its regime. Without this the
    memory would only ever exist in unit tests."""
    corpus = tmp_path / "corpus"
    _corpus_with_profile(corpus, "house", hooks=None)
    monkeypatch.setenv("CORPUS_ROOT", str(corpus))
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)

    repo = tmp_path / "pinky-fresh"
    setup._init_repo_skeleton(repo)
    monkeypatch.setattr(setup.precommit, "discover_repos", lambda: [repo])
    # See test_drift_extra_hooks.py: prek / detect-secrets are an external boundary, present on the
    # author's PATH and absent from the CI runner's — stubbed so the tooling gate cannot decide the
    # outcome of a test about the profile record.
    monkeypatch.setattr(setup.precommit, "_prek_install", lambda *_a, **_k: None)
    monkeypatch.setattr(
        setup.precommit, "_ensure_secrets_baseline", lambda *_a, **_k: None
    )

    setup.run_distribution(
        _args(all=False, repo="pinky-fresh", profile="house", dry_run=False)
    )

    written = json.loads(
        (repo / "scripts" / "hooks" / "docs_identity.json").read_text(encoding="utf-8")
    )
    assert written["profile"] == "house"
    assert setup.repo_profile(repo) == "house"
