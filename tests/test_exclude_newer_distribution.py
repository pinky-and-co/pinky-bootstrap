"""Oracles for `render_pyproject_with_exclude_newer` (chantier-0024, template-exclude-newer).

A hand-typed `[tool.uv] exclude-newer` date, duplicated identically across 12 repos, meant renewing
the cooldown window was 12 manual edits instead of one. This generates the line the same way
`render_ci_yml` generates `ci.yml` — only the `exclude-newer` line changes, nothing else in the
file is touched.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod  # noqa: E402


@pytest.fixture
def repo_with_exclude_newer(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\n\n'
        "# Cooldown comment, kept verbatim.\n"
        "[tool.uv]\n"
        'preview-features = ["centralized-project-envs"]\n'
        '# Another comment.\nexclude-newer = "2020-01-01T00:00:00Z"\n\n'
        "[tool.other]\nkey = 1\n",
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def repo_with_tool_uv_no_exclude_newer(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\n\n[tool.uv]\npreview-features = ["x"]\n',
        encoding="utf-8",
    )
    return repo


@pytest.fixture
def repo_without_tool_uv(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\n', encoding="utf-8"
    )
    return repo


@pytest.fixture
def repo_without_pyproject(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    return repo


def test_cutoff_is_the_configured_number_of_days_before_today():
    expected = date.today() - timedelta(days=precommit_mod.EXCLUDE_NEWER_DAYS)
    assert precommit_mod.exclude_newer_cutoff() == f"{expected.isoformat()}T00:00:00Z"


def test_updates_only_the_exclude_newer_line(repo_with_exclude_newer):
    new_text = precommit_mod.render_pyproject_with_exclude_newer(
        repo_with_exclude_newer, "2099-01-01T00:00:00Z"
    )
    assert new_text == (
        '[project]\nname = "pinky-fake"\n\n'
        "# Cooldown comment, kept verbatim.\n"
        "[tool.uv]\n"
        'preview-features = ["centralized-project-envs"]\n'
        '# Another comment.\nexclude-newer = "2099-01-01T00:00:00Z"\n\n'
        "[tool.other]\nkey = 1\n"
    )


def test_is_a_noop_when_the_cutoff_already_matches(repo_with_exclude_newer):
    assert (
        precommit_mod.render_pyproject_with_exclude_newer(
            repo_with_exclude_newer, "2020-01-01T00:00:00Z"
        )
        is None
    )


def test_inserts_the_line_when_tool_uv_exists_without_it(
    repo_with_tool_uv_no_exclude_newer,
):
    new_text = precommit_mod.render_pyproject_with_exclude_newer(
        repo_with_tool_uv_no_exclude_newer, "2099-01-01T00:00:00Z"
    )
    assert new_text == (
        '[project]\nname = "pinky-fake"\n\n[tool.uv]\n'
        + precommit_mod.EXCLUDE_NEWER_COMMENT
        + 'exclude-newer = "2099-01-01T00:00:00Z"\npreview-features = ["x"]\n'
    )


def test_creates_a_tool_uv_section_when_absent(repo_without_tool_uv):
    new_text = precommit_mod.render_pyproject_with_exclude_newer(
        repo_without_tool_uv, "2099-01-01T00:00:00Z"
    )
    assert new_text == (
        '[project]\nname = "pinky-fake"\n\n[tool.uv]\n'
        + precommit_mod.EXCLUDE_NEWER_COMMENT
        + 'exclude-newer = "2099-01-01T00:00:00Z"\n'
    )


def test_returns_none_without_a_pyproject_toml(repo_without_pyproject):
    assert (
        precommit_mod.render_pyproject_with_exclude_newer(
            repo_without_pyproject, "2099-01-01T00:00:00Z"
        )
        is None
    )
