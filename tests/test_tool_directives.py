"""tool_directives.py — one table of the inline directives the toolchain reads."""

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
import tool_directives as td
from setup.common import CORE_PRECOMMIT_DIR


def _precommit_hook_ids() -> set[str]:
    ids: set[str] = set()
    for config in CORE_PRECOMMIT_DIR.rglob("*.yaml"):
        text = config.read_text(encoding="utf-8")
        ids |= set(re.findall(r"^\s*- id: ([\w-]+)", text, flags=re.MULTILINE))
    return ids


def test_every_precommit_hook_is_covered_or_declared_directive_free():
    covered = {i for d in td.DIRECTIVES for i in d.hook_ids} | set(
        td.NO_DIRECTIVE_HOOKS
    )
    assert sorted(_precommit_hook_ids() - covered) == []


def test_no_table_entry_names_a_hook_that_does_not_exist():
    named = {i for d in td.DIRECTIVES for i in d.hook_ids} | set(td.NO_DIRECTIVE_HOOKS)
    assert sorted(named - _precommit_hook_ids()) == []


def test_every_example_is_a_directive_the_regex_keeps():
    for d in td.DIRECTIVES:
        comment = d.example[d.example.index("#") :]
        assert td.DIRECTIVE_RE.match(comment), d.tool


def test_lookup_prints_the_line_to_paste():
    assert td.format_lookup("E402") == [f"{'ruff':<15} # noqa: E402"]
    assert td.format_lookup("[type-arg]") == [f"{'mypy':<15} # type: ignore[type-arg]"]
    assert td.format_lookup("DAR101") == [
        f"{'darglint':<15} # noqa: DAR101  (a line of the docstring)"
    ]
    assert td.format_lookup("SNOWPARK-SQL-INLINE") == [
        f"{'pinky snowpark':<15} # pinky: SNOWPARK-SQL-INLINE"
    ]


def test_lookup_shows_every_tool_sharing_a_code_shape():
    assert td.format_lookup("B608") == [
        f"{'ruff':<15} # noqa: B608",
        f"{'bandit':<15} # nosec B608",
    ]


def test_unknown_code_points_at_the_table():
    assert td.format_lookup("42") == [
        "no known tool reports '42' — `pinky directives` lists them all"
    ]


def test_cheat_sheet_has_one_line_per_tool():
    assert len(td.format_lookup(None)) == len(td.DIRECTIVES)


def test_snowpark_hook_markers_are_in_the_table():
    source = (setup.CORE_HOOKS_DIR / "check_snowpark_api.py").read_text(
        encoding="utf-8"
    )
    pinky = next(d for d in td.DIRECTIVES if d.tool == "pinky snowpark")
    for code in sorted(set(re.findall(r"# pinky: ([A-Z-]+)", source))):
        assert re.fullmatch(pinky.codes, code), code


def test_runs_standalone_in_a_repo_without_the_cli():
    run = subprocess.run(
        [sys.executable, str(setup.CORE_HOOKS_DIR / "tool_directives.py"), "E402"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0
    assert run.stdout == f"{'ruff':<15} # noqa: E402\n"
