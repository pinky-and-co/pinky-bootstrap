"""Oracles for `render_pyproject_with_cooldown`.

`[tool.uv] exclude-newer` is a **relative** cooldown span (`"3 days"`, uv >= 0.9.17), not an
absolute date: uv resolves it at every `uv lock` and records `exclude-newer-span` in `uv.lock`, so
`pinky repo distribute` writes the line once and never rewrites it — no window to renew, no `uv.lock`
desync. The generator also pins `required-version` so an older uv fails loudly instead of silently
ignoring the relative span.

`exclude-newer-package` (the per-package exemption map) belongs to each repo: distribute never
writes, converts, moves or removes it, in whatever spelling the repo declares it.

Every generator gets a whole-output equality oracle (rules/tests.md): a fragment assertion passes
on the correct output and on a wrong one.
"""

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod

_HEADER = '[project]\nname = "pinky-fake"\n\n'
_REQUIRED = f'required-version = "{precommit_mod.UV_REQUIRED_VERSION}"\n'
_COOLDOWN = (
    precommit_mod.COOLDOWN_COMMENT
    + f'exclude-newer = "{precommit_mod.EXCLUDE_NEWER_SPAN}"\n'
)
_MAP = 'exclude-newer-package = { pinky-core = "2999-01-01T00:00:00Z" }\n'


def _write(repo: Path, pyproject: str) -> Path:
    repo.mkdir()
    (repo / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return repo


@pytest.fixture
def repo_with_absolute_date(tmp_path):
    return _write(
        tmp_path / "pinky-fake",
        _HEADER + "[tool.uv]\n"
        'preview-features = ["centralized-project-envs"]\n'
        "# Ancien blabla de cooldown, remplacé en bloc.\n"
        'exclude-newer = "2020-01-01T00:00:00Z"\n\n'
        "[tool.other]\nkey = 1\n",
    )


@pytest.fixture
def repo_with_tool_uv_only(tmp_path):
    return _write(
        tmp_path / "pinky-fake", _HEADER + '[tool.uv]\npreview-features = ["x"]\n'
    )


@pytest.fixture
def repo_without_tool_uv(tmp_path):
    return _write(tmp_path / "pinky-fake", '[project]\nname = "pinky-fake"\n')


def test_replaces_absolute_date_block_and_inserts_required_version(
    repo_with_absolute_date,
):
    assert precommit_mod.render_pyproject_with_cooldown(repo_with_absolute_date) == (
        _HEADER
        + "[tool.uv]\n"
        + _REQUIRED
        + 'preview-features = ["centralized-project-envs"]\n'
        + _COOLDOWN
        + "\n[tool.other]\nkey = 1\n"
    )


def test_inserts_both_keys_when_tool_uv_exists_without_them(repo_with_tool_uv_only):
    assert precommit_mod.render_pyproject_with_cooldown(repo_with_tool_uv_only) == (
        _HEADER + "[tool.uv]\n" + _REQUIRED + _COOLDOWN + 'preview-features = ["x"]\n'
    )


def test_creates_a_tool_uv_section_when_absent(repo_without_tool_uv):
    assert precommit_mod.render_pyproject_with_cooldown(repo_without_tool_uv) == (
        _HEADER + "[tool.uv]\n" + _REQUIRED + _COOLDOWN
    )


def test_is_a_noop_when_already_compliant(tmp_path):
    repo = _write(
        tmp_path / "pinky-fake", _HEADER + "[tool.uv]\n" + _REQUIRED + _COOLDOWN
    )
    assert precommit_mod.render_pyproject_with_cooldown(repo) is None


def test_is_idempotent(repo_with_absolute_date):
    once = precommit_mod.render_pyproject_with_cooldown(repo_with_absolute_date)
    assert once is not None
    (repo_with_absolute_date / "pyproject.toml").write_text(once, encoding="utf-8")
    assert precommit_mod.render_pyproject_with_cooldown(repo_with_absolute_date) is None


def test_tool_uv_sources_header_is_never_matched(tmp_path):
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER
        + '[tool.uv.sources]\npinky-core = { path = "../pinky-core" }\n\n'
        + '[tool.uv]\npreview-features = ["x"]\n',
    )
    assert precommit_mod.render_pyproject_with_cooldown(repo) == (
        _HEADER
        + '[tool.uv.sources]\npinky-core = { path = "../pinky-core" }\n\n'
        + "[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN
        + 'preview-features = ["x"]\n'
    )


def test_keeps_a_hand_pinned_newer_required_version(tmp_path):
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER + '[tool.uv]\nrequired-version = ">=0.10"\n'
        'exclude-newer = "2020-01-01T00:00:00Z"\n',
    )
    out = precommit_mod.render_pyproject_with_cooldown(repo)
    assert out is not None
    assert out == (_HEADER + '[tool.uv]\nrequired-version = ">=0.10"\n' + _COOLDOWN)
    assert f'"{precommit_mod.UV_REQUIRED_VERSION}"' not in out


def test_freezes_the_literal_keys(repo_with_tool_uv_only):
    """The two values the whole change hinges on, pinned as literal text (not rebuilt from the
    module) so a typo in a constant — `">=0.9.7"`, `"3 day"` — is caught here."""
    out = precommit_mod.render_pyproject_with_cooldown(repo_with_tool_uv_only)
    assert out is not None
    assert 'exclude-newer = "3 days"\n' in out
    assert 'required-version = ">=0.9.17"\n' in out


def test_required_version_in_another_table_does_not_suppress_the_uv_one(tmp_path):
    """`required-version` is also a `[tool.ruff]` key — the guard must scope to `[tool.uv]`."""
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER
        + '[tool.ruff]\nrequired-version = ">=0.6"\n\n'
        + '[tool.uv]\npreview-features = ["x"]\n',
    )
    assert precommit_mod.render_pyproject_with_cooldown(repo) == (
        _HEADER
        + '[tool.ruff]\nrequired-version = ">=0.6"\n\n'
        + "[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN
        + 'preview-features = ["x"]\n'
    )


def test_exclude_newer_under_tool_uv_pip_is_left_alone(tmp_path):
    """`exclude-newer` is also valid under `[tool.uv.pip]` — only the bare `[tool.uv]` table is ours."""
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER
        + '[tool.uv]\npreview-features = ["x"]\n\n'
        + '[tool.uv.pip]\nexclude-newer = "2019-01-01T00:00:00Z"\n',
    )
    assert precommit_mod.render_pyproject_with_cooldown(repo) == (
        _HEADER
        + "[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN
        + 'preview-features = ["x"]\n\n'
        + '[tool.uv.pip]\nexclude-newer = "2019-01-01T00:00:00Z"\n'
    )


def test_returns_none_without_a_pyproject_toml(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    assert precommit_mod.render_pyproject_with_cooldown(repo) is None


def test_a_hand_written_exemption_map_is_left_alone(tmp_path):
    """The map is the repo's: whatever it holds and wherever it sits in `[tool.uv]`, distribute
    keeps it byte for byte beside the window and the required version."""
    comment = "# Exemption écrite à la main.\n"
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER + "[tool.uv]\n" + comment + _MAP + 'preview-features = ["x"]\n',
    )
    out = precommit_mod.render_pyproject_with_cooldown(repo)
    assert out == (
        _HEADER
        + "[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN
        + comment
        + _MAP
        + 'preview-features = ["x"]\n'
    )
    assert out is not None
    assert tomllib.loads(out)["tool"]["uv"]["exclude-newer-package"] == {
        "pinky-core": "2999-01-01T00:00:00Z"
    }


def test_a_multiline_exemption_map_is_left_alone(tmp_path):
    multiline = (
        'exclude-newer-package = { pinky-core = "2999-01-01T00:00:00Z",\n'
        '  pinky-snowpark = "2999-01-01T00:00:00Z" }\n'
    )
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER + "[tool.uv]\n" + _REQUIRED + _COOLDOWN + multiline,
    )
    assert precommit_mod.render_pyproject_with_cooldown(repo) is None


def test_an_exemption_subtable_is_left_alone(tmp_path):
    subtable = '[tool.uv.exclude-newer-package]\npinky-core = "2999-01-01T00:00:00Z"\n'
    repo = _write(
        tmp_path / "pinky-fake",
        _HEADER + "[tool.uv]\n" + 'preview-features = ["x"]\n\n' + subtable,
    )
    out = precommit_mod.render_pyproject_with_cooldown(repo)
    assert out == (
        _HEADER
        + "[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN
        + 'preview-features = ["x"]\n\n'
        + subtable
    )
    assert out is not None
    assert tomllib.loads(out)["tool"]["uv"]["exclude-newer-package"] == {
        "pinky-core": "2999-01-01T00:00:00Z"
    }


def test_an_exemption_subtable_without_a_bare_tool_uv_stays_valid_toml(tmp_path):
    subtable = '[tool.uv.exclude-newer-package]\npinky-core = "2999-01-01T00:00:00Z"\n'
    repo = _write(tmp_path / "pinky-fake", _HEADER + subtable)
    out = precommit_mod.render_pyproject_with_cooldown(repo)
    assert (
        out
        == _HEADER
        + subtable
        + "\n[tool.uv]\n"
        + _REQUIRED
        + _COOLDOWN.rstrip("\n")
        + "\n"
    )
    assert out is not None
    uv = tomllib.loads(out)["tool"]["uv"]
    assert uv["exclude-newer"] == "3 days"
    assert uv["exclude-newer-package"] == {"pinky-core": "2999-01-01T00:00:00Z"}


def test_distribution_never_writes_an_exemption_map(repo_with_tool_uv_only):
    out = precommit_mod.render_pyproject_with_cooldown(repo_with_tool_uv_only)
    assert out is not None
    assert "exclude-newer-package" not in out
