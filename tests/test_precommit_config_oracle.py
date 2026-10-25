"""Equality + grammar oracles for `build_precommit_config`.

`build_precommit_config` was the workspace's heaviest fragment-only generator (`tests.md` §
"assertions on generated output"): every existing test asserts `f"id: {pcid}" in cfg`, which is
true of a correct config AND of a text concat that broke the YAML — the assembled file is built by
**string concatenation of YAML fragments**, so a duplicated `repos:` key, a lost blank line or a
mis-indented fragment produces a file prek refuses to load while every substring still matches.

Two oracles:

1. **Assembly** — a hermetic `CORE_PRECOMMIT_DIR` of stub fragments, whole-output equality. Pins
   fragment order, the single blank line between them, the trailing newline and the mypy
   placeholder substitution, with no dependency on the real hook set (which changes constantly).
2. **Grammar** — the REAL fragments, parsed and checked against pre-commit's documented config
   schema (https://pre-commit.com/#pre-commit-configyaml---top-level, `- hooks`, § Repository local
   hooks). This is the third-party contract the file must satisfy — verified against the tool's
   grammar, never against a snapshot of what pinky emits today.
"""

import sys
from pathlib import Path

import pytest

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402
from setup import precommit as precommit_mod  # noqa: E402

TOP_LEVEL_KEYS = {
    "repos",
    "default_install_hook_types",
    "default_language_version",
    "default_stages",
    "files",
    "exclude",
    "fail_fast",
    "minimum_pre_commit_version",
    "ci",
}
REPO_KEYS = {"repo", "rev", "hooks"}
HOOK_KEYS = {
    "id",
    "alias",
    "name",
    "entry",
    "language",
    "language_version",
    "files",
    "exclude",
    "types",
    "types_or",
    "exclude_types",
    "args",
    "stages",
    "additional_dependencies",
    "always_run",
    "fail_fast",
    "verbose",
    "log_file",
    "pass_filenames",
    "require_serial",
    "description",
    "minimum_pre_commit_version",
}


# ── 1. assembly oracle (hermetic) ─────────────────────────────────────────────

BASE_STUB = """---
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - id: end-of-file-fixer
"""

PYTHON_STUB = """  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: mypy
        language: python
        additional_dependencies: __MYPY_DEPS__
"""

WEB_STUB = """  - repo: local
    hooks:
      - id: js-file-size
        name: js-file-size
        entry: scripts/hooks/check_js_size.py
        language: python
"""


@pytest.fixture
def stub_fragments(tmp_path, monkeypatch):
    """A CORE_PRECOMMIT_DIR holding stub fragments only — the assembly is then a pure function of
    text the test owns, so the equality oracle survives every real hook bump."""
    core = tmp_path / "pre-commit"
    (core / "extras").mkdir(parents=True)
    (core / "base.yaml").write_text(BASE_STUB, encoding="utf-8")
    (core / "extras" / "python.yaml").write_text(PYTHON_STUB, encoding="utf-8")
    (core / "extras" / "web.yaml").write_text(WEB_STUB, encoding="utf-8")
    monkeypatch.setattr(precommit_mod, "CORE_PRECOMMIT_DIR", core)
    monkeypatch.setattr(
        precommit_mod, "MYPY_DEPS_PLACEHOLDER", "__MYPY_DEPS__", raising=False
    )
    return core


def test_build_precommit_config_oracle_base_plus_extras(tmp_path, stub_fragments):
    """Oracle — the WHOLE assembled file.

    Pins what fragment asserts are structurally blind to: base comes first (it carries the single
    `repos:` key every following fragment is a list item OF), extras follow in the order given,
    fragments are separated by exactly one blank line, the file ends with exactly one newline, and
    the mypy placeholder is replaced by a **YAML-quoted list** (an unquoted `pydantic>=2` would make
    prek choke on the `>`). Only the pin VALUE is read from the constant — the list syntax around
    it, which is what the generator actually builds, stays spelled out.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=['pydantic>=2']\n", encoding="utf-8"
    )
    assert setup.build_precommit_config(tmp_path, ["python", "web"]) == (
        "---\n"
        "repos:\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
        "    rev: v6.0.0\n"
        "    hooks:\n"
        "      - id: end-of-file-fixer\n"
        "\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: mypy\n"
        "        name: mypy\n"
        "        entry: mypy\n"
        "        language: python\n"
        f'        additional_dependencies: ["mypy=={precommit_mod.MYPY_PIN}", "pydantic>=2"]\n'
        "\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: js-file-size\n"
        "        name: js-file-size\n"
        "        entry: scripts/hooks/check_js_size.py\n"
        "        language: python\n"
    )


def test_build_precommit_config_oracle_unknown_extra_is_skipped(
    tmp_path, stub_fragments
):
    """Oracle — an extra with no fragment on disk contributes nothing and leaves the rest intact
    (no stray blank line, no partial section)."""
    assert setup.build_precommit_config(tmp_path, ["nope"]) == BASE_STUB


# ── 2. grammar oracle (real fragments, pre-commit schema) ─────────────────────


@pytest.mark.parametrize(
    "extras",
    [[], ["python"], ["python", "snowflake"], ["web"], ["python-lint"]],
    ids=["base", "python", "snowflake", "web", "python-lint"],
)
def test_assembled_config_matches_the_precommit_grammar(tmp_path, extras):
    """Every real extras combination parses as a VALID .pre-commit-config.yaml.

    Checks the whole parsed document node by node against pre-commit's documented grammar: a single
    top-level mapping (the concat must not restart `repos:`), only known top-level keys, each repo
    entry a mapping of known keys with a `hooks` list, and every hook carrying an `id` plus — for
    `repo: local` — the `name`/`entry`/`language` the docs make mandatory. A broken concat fails
    here; `"id: x" in cfg` would not.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=[]\n", encoding="utf-8"
    )
    cfg = yaml.safe_load(setup.build_precommit_config(tmp_path, extras))

    assert isinstance(cfg, dict)
    assert set(cfg) <= TOP_LEVEL_KEYS, (
        f"unknown top-level key(s): {set(cfg) - TOP_LEVEL_KEYS}"
    )
    assert isinstance(cfg["repos"], list) and cfg["repos"]

    for entry in cfg["repos"]:
        assert set(entry) <= REPO_KEYS, f"unknown repo key(s): {set(entry) - REPO_KEYS}"
        assert isinstance(entry.get("hooks"), list) and entry["hooks"]
        if entry["repo"] != "local":
            assert entry.get("rev"), (
                f"remote repo without a pinned rev: {entry['repo']}"
            )
        for hook in entry["hooks"]:
            assert set(hook) <= HOOK_KEYS, (
                f"unknown hook key(s): {set(hook) - HOOK_KEYS}"
            )
            assert hook.get("id")
            if entry["repo"] == "local":
                for required in ("name", "entry", "language"):
                    assert hook.get(required), (
                        f"local hook {hook['id']} misses `{required}` "
                        "(mandatory per pre-commit's local-hooks docs)"
                    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
