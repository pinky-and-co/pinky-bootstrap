"""check_narrative_comments.py — blocking detector of history narrated in comments and docstrings."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "check_narrative_comments.py"

_spec = importlib.util.spec_from_file_location("check_narrative_comments", HOOK)
cnc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cnc)


def _scan(src: str, tmp_path: Path) -> list[tuple[int, str]]:
    f = tmp_path / "sample.py"
    f.write_text(src, encoding="utf-8")
    return [(finding.line, finding.kinds) for finding in cnc.check_file(f)]


def test_comment_history_is_flagged_by_kind(tmp_path):
    src = (
        "a = 1  # decided 2026-07-24\n"
        "b = 2  # covers FR-0025-12\n"
        "c = 3  # see CHANTIER0001\n"
        "d = 4  # see card `site-mkdocs`\n"
    )
    assert _scan(src, tmp_path) == [
        (1, "date"),
        (2, "requirement id"),
        (3, "chantier ref"),
        (4, "card ref"),
    ]


def test_comment_file_ref_is_flagged(tmp_path):
    src = (
        "a = 1  # same fix as setup/__init__.py\n"
        "b = 2  # reads pyproject.toml\n"
        "c = 3  # lives under scripts/hooks/\n"
        "d = 4  # engine.min.js must follow\n"
    )
    assert _scan(src, tmp_path) == [
        (1, "file ref"),
        (2, "file ref"),
        (3, "file ref"),
        (4, "file ref"),
    ]


def test_comment_without_file_ref_is_clean(tmp_path):
    src = (
        "a = 1  # read and/or write, e.g. twice\n"
        "b = 2  # pinned to v1.7.0, see https://pre-commit.com/hooks.html\n"
        "c = 3  # the Windows console can't encode the output\n"
        "d = 4  # receivers whose session.sql() call is not Snowpark\n"
    )
    assert _scan(src, tmp_path) == []


def test_docstring_history_is_flagged_on_its_own_line(tmp_path):
    src = (
        "def f():\n"
        '    """Return one.\n'
        "\n"
        "    Decided 2026-07-24, see card `x-y`.\n"
        '    """\n'
        "    return 1\n"
    )
    assert _scan(src, tmp_path) == [(4, "date, card ref")]


def test_docstring_may_name_a_file(tmp_path):
    src = 'def f():\n    """Read settings from pyproject.toml."""\n'
    assert _scan(src, tmp_path) == []


def test_hash_inside_a_string_is_not_a_comment(tmp_path):
    src = 'url = "https://x.org/a#2026-07-24"\nlabel = "# see FR-0025-12"\n'
    assert _scan(src, tmp_path) == []


def test_directives_and_pep723_are_skipped(tmp_path):
    src = (
        "#!/usr/bin/env python3\n"
        "# /// script\n"
        "# [tool.uv]\n"
        '# exclude-newer = "2026-01-01"\n'
        "# ///\n"
        "import setup  # noqa: E402\n"
        "x = setup.f()  # type: ignore[arg-type]\n"
    )
    assert _scan(src, tmp_path) == []


def test_comment_block_past_three_lines_is_flagged_once(tmp_path):
    src = "# one\n# two\n# three\n# four\nx = 1\n# a\n# b\n# c\ny = 2\n"
    assert _scan(src, tmp_path) == [(1, "long comment (4 lines)")]


def test_blank_line_trailing_comment_or_directive_break_a_block(tmp_path):
    src = "# a\n# b\n\n# c\n# d\nx = 1  # e\n# f\n# g\n# type: ignore\n# h\n# i\n"
    assert _scan(src, tmp_path) == []


def test_long_block_merges_with_history_on_its_first_line(tmp_path):
    src = "# decided 2026-07-24\n# b\n# c\n# d\n"
    assert _scan(src, tmp_path) == [(1, "date, long comment (4 lines)")]


def test_unparsable_file_is_skipped(tmp_path):
    assert _scan("def (:\n    # 2026-07-24\n", tmp_path) == []


def test_findings_print_path_and_line_and_block(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("a = 1  # decided 2026-07-24\n", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 1
    assert (
        run.stdout.splitlines()[0]
        == f"⚠️  [NARRATIVE] {f}:1: date: # decided 2026-07-24"
    )


def test_clean_file_passes_silently(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text("a = 1  # read and/or write, e.g. twice\n", encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0
    assert run.stdout == ""


def test_warn_only_hooks_are_verbose(tmp_path):
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(setup.build_precommit_config(tmp_path, ["web"]))
    hooks = {hook["id"]: hook for repo in cfg["repos"] for hook in repo["hooks"]}
    for pcid in ("js-file-size", "js-structure", "html-inline-js"):
        assert hooks[pcid].get("verbose") is True
