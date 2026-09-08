"""Auto-derived lint scope for the `python` extra's src/-scoped hooks (mypy/bandit/darglint/
interrogate/check-typed-api), for a repo with a `pyproject.toml` but no `src/` layout.

Before this, those five hooks all carried a hardcoded `files: ^src/` — a correct assumption for a
src/-layout package, a silent no-op for a flat-layout one (measured: `pinky-bootstrap` itself, 0
`.py` under `src/`, real code in `setup/`/`hygiene/`/`tools/`/`cli_pinky.py` went unchecked since
the day this repo grew a `pyproject.toml`). Same failure mode `run-tests`' own `files:` filter had
(see that hook's comment in base.yaml) — an allowlist of layouts, wrong by default for any layout
not on the list. `_py_lint_roots` fixes it the same way: derive the scope from what is actually on
disk, no per-repo table to keep in sync.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

# ── _py_lint_roots ─────────────────────────────────────────────────────────────


def test_src_layout_returns_src_unchanged(tmp_path):
    """The common case stays exactly what it always was — no drift for the 9 real src/ repos."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg.py").write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == ["src/"]


def test_src_dir_wins_even_with_other_top_level_py(tmp_path):
    """A repo migrating TO src/ mid-transition must not also sweep in the dirs it is leaving —
    src/ present is the whole signal, nothing else is consulted."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg.py").write_text("", encoding="utf-8")
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "old.py").write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == ["src/"]


def test_flat_layout_discovers_dirs_and_loose_files(tmp_path):
    for rel in ("setup/cli.py", "hygiene/hook.py", "tools/one.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    (tmp_path / "cli_pinky.py").write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == [
        "cli_pinky.py",
        "hygiene/",
        "setup/",
        "tools/",
    ]


def test_flat_layout_excludes_scripts_hooks_distributed_paths(tmp_path):
    """scripts/hooks/ is DISTRIBUTED_PATHS — never authored by this repo, same exclusion
    `resolve_extras` already applies when deciding the `python-lint` extra."""
    p = tmp_path / "scripts" / "hooks" / "check_zws.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == []


def test_flat_layout_includes_scripts_content_outside_hooks(tmp_path):
    """Only scripts/hooks/ is excluded — a repo authoring something else under scripts/ keeps it."""
    p = tmp_path / "scripts" / "release.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == ["scripts/"]


def test_flat_layout_excludes_tests(tmp_path):
    p = tmp_path / "tests" / "test_x.py"
    p.parent.mkdir(parents=True)
    p.write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == []


def test_flat_layout_excludes_hidden_and_cache_dirs(tmp_path):
    for rel in (
        ".venv/lib/site.py",
        "__pycache__/mod.pyc".replace(".pyc", ".py"),
        ".git/hooks/x.py",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    assert setup.precommit._py_lint_roots(tmp_path) == []


def test_flat_layout_with_no_py_at_all_is_empty(tmp_path):
    assert setup.precommit._py_lint_roots(tmp_path) == []


# ── rendering helpers ───────────────────────────────────────────────────────────


def test_files_pattern_for_src() -> None:
    assert setup.precommit._py_lint_files_pattern(["src/"]) == "^src/"


def test_files_pattern_for_flat_layout_roots() -> None:
    """`.` in a loose filename is a literal dot, not "any char" — re.escape's job."""
    assert setup.precommit._py_lint_files_pattern(
        ["cli_pinky.py", "hygiene/", "setup/"]
    ) == (r"^cli_pinky\.py$|^hygiene/|^setup/")


def test_files_pattern_for_no_roots_never_matches() -> None:
    pattern = setup.precommit._py_lint_files_pattern([])
    import re

    assert re.search(pattern, "anything/at/all.py") is None
    assert re.search(pattern, "") is None


def test_bandit_args_for_src() -> None:
    assert (
        setup.precommit._py_lint_bandit_args(["src/"])
        == "[-r, src/, -ll, --skip, B108]"
    )


def test_interrogate_args_for_src() -> None:
    assert setup.precommit._py_lint_interrogate_args(["src/"]) == (
        "[src/, --ignore-init-method, --ignore-magic, --ignore-module, --ignore-private]"
    )


def test_bandit_args_for_flat_layout_roots() -> None:
    assert setup.precommit._py_lint_bandit_args(["cli_pinky.py", "setup/"]) == (
        "[-r, cli_pinky.py, setup/, -ll, --skip, B108]"
    )


# ── build_precommit_config, real fragments ──────────────────────────────────────


def test_src_layout_config_is_byte_identical_to_historical_src_scope(tmp_path):
    """The regression guard for the whole change: a repo with `src/` must generate the exact same
    `files:`/`args:` text it always did — `^src/`, `[-r, src/, ...]`, `[src/, ...]` — so the 9 real
    src/ repos see no diff from this."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pkg.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=[]\n", encoding="utf-8"
    )
    cfg = setup.build_precommit_config(tmp_path, ["python"])
    assert setup.precommit.PY_LINT_FILES_PLACEHOLDER not in cfg
    assert "files: ^src/\n" in cfg
    assert "args: [-r, src/, -ll, --skip, B108]\n" in cfg
    assert (
        "args: [src/, --ignore-init-method, --ignore-magic, --ignore-module, "
        "--ignore-private]\n"
    ) in cfg


def test_flat_layout_config_scopes_hooks_to_discovered_roots(tmp_path):
    for rel in ("setup/cli.py", "hygiene/hook.py"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=[]\n", encoding="utf-8"
    )
    cfg = setup.build_precommit_config(tmp_path, ["python"])
    assert "files: ^hygiene/|^setup/\n" in cfg
    assert "args: [-r, hygiene/, setup/, -ll, --skip, B108]\n" in cfg


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
