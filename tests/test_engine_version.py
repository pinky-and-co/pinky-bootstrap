"""Card `versionner-le-moteur`: the moteur had no version at all — no `__version__`, no tag, no
`pyproject.toml` — the angle blind ADR-0065's own council found under its best idea (`engine_version`
in docs_identity.json presupposes a version that did not exist).

`engine_version()` has two sources on purpose: `importlib.metadata` reads the INSTALLED
distribution (the `uv tool install git+<url>` shape ADR-0065 decision 5 picked), which is the only
one that survives SCRIPT_DIR pointing inside a venv instead of a checkout. The `pyproject.toml`
fallback covers the shape this very repo is run in today — a plain clone, `python3 setup.py`, never
`pip install`-ed, so there is no distribution metadata to query at all.
"""

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402
from setup.common import metadata  # noqa: E402

IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


# ── engine_version — the two sources ──────────────────────────────────────────


def test_engine_version_prefers_installed_metadata(monkeypatch):
    """When the moteur is a real installed distribution, its metadata is authoritative — never
    fall through to reading pyproject.toml off disk, which may not even ship in the wheel."""
    monkeypatch.setattr(metadata, "version", lambda _name: "9.9.9")
    assert setup.engine_version() == "9.9.9"


def test_engine_version_falls_back_to_this_repos_pyproject_when_not_installed(
    monkeypatch,
):
    """Today's real shape: a clone, run via `python3 setup.py`, never `pip install`-ed. Must read
    the SAME pyproject.toml this repo ships, not a hardcoded guess."""

    def _not_installed(_name):
        raise metadata.PackageNotFoundError

    monkeypatch.setattr(metadata, "version", _not_installed)
    expected = tomllib.loads(
        (setup.SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    assert setup.engine_version() == expected


# ── check_drift — version lag is reported, never fatal ───────────────────────


def _distributed_repo(tmp_path: Path, name: str = "pinky-thing") -> Path:
    repo = tmp_path / name
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY)
    return repo


def test_check_drift_reports_a_version_lagging_repo(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    repo = _distributed_repo(tmp_path)

    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev2")
    total = setup.check_drift([repo])

    out = capsys.readouterr().out
    assert "pinky-thing: v0.1.0.dev1 → pinky distribute --repo pinky-thing" in out
    assert total == 0, "version lag alone must never turn the gate red"


def test_check_drift_is_silent_on_a_repo_never_carrying_the_key(
    tmp_path, monkeypatch, capsys
):
    """A repo distributed before `engine_version` existed (the whole parc, pre `versionner-le-moteur`)
    reads as unknown — reporting a false lag would be worse than reporting nothing."""
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    repo = tmp_path / "pinky-legacy"
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY)
    (repo / "scripts" / "hooks" / "docs_identity.json").write_text(
        IDENTITY.to_json(), encoding="utf-8"
    )

    setup.check_drift([repo])

    assert "behind engine" not in capsys.readouterr().out


def test_check_drift_reports_no_lag_when_versions_match(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.precommit, "engine_version", lambda: "0.1.0.dev1")
    repo = _distributed_repo(tmp_path)

    setup.check_drift([repo])

    assert "behind engine" not in capsys.readouterr().out


# ── check_drift — `.cache/` convention gap is advisory, never fatal ──────────
# (card `convention-cache-jamais-distribuee`: pyproject.toml is repo-owned, distribute() can't fix
# it, so — same reasoning as version lag above — it must never turn the gate red.)


def test_check_drift_reports_a_repo_missing_the_cache_convention(
    tmp_path, monkeypatch, capsys
):
    repo = _distributed_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[tool.ruff]\nline-length = 88\n", encoding="utf-8"
    )
    # Redistribute so hooks/.pre-commit-config.yaml catch up with the now-present pyproject.toml
    # (extras resolution reads it) — isolates the cache gap as the ONLY remaining divergence.
    setup.distribute(repo, dry_run=False, identity=IDENTITY)

    total = setup.check_drift([repo])

    out = capsys.readouterr().out
    assert "missing/wrong cache-dir" in out
    assert total == 0, "a repo-owned pyproject.toml gap must never turn the gate red"


# Direct unit coverage of the pure query (no distribute() dance needed — writing a pyproject.toml
# on top of a distributed repo would itself shift resolve_extras()'s verdict, entangling these
# "nothing to report" cases with unrelated .pre-commit-config.yaml drift; the one check_drift
# integration test above already proves the wiring end to end).


def test_cache_convention_issues_silent_when_convention_present(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\ncache-dir = ".cache/ruff"\n', encoding="utf-8"
    )
    assert setup.precommit._cache_convention_issues(tmp_path) == []


def test_cache_convention_issues_silent_when_tool_section_absent_entirely(tmp_path):
    # A repo that doesn't even configure mypy isn't missing anything — only a SECTION already
    # present without the cache-dir key is a real gap.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8"
    )
    assert setup.precommit._cache_convention_issues(tmp_path) == []


def test_cache_convention_issues_silent_when_no_pyproject_at_all(tmp_path):
    assert setup.precommit._cache_convention_issues(tmp_path) == []


def test_cache_convention_issues_flags_the_missing_key(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.mypy]\nstrict = true\n", encoding="utf-8"
    )
    issues = setup.precommit._cache_convention_issues(tmp_path)
    assert issues == [
        "pyproject.toml [tool.mypy] missing/wrong cache_dir = '.cache/mypy'"
    ]
