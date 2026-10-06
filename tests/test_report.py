"""_report.py — the ruff-style renderer shared by the hygiene hooks."""

import importlib.util
import io
import re
from pathlib import Path

import pytest

import setup

_spec = importlib.util.spec_from_file_location(
    "_report", setup.CORE_HOOKS_DIR / "_report.py"
)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

Diagnostic = report.Diagnostic


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """Two files under `src/pkg/`, the paths relative to the working directory."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "src/pkg/a.py").write_text("x = 1\nimport os, sys\n", encoding="utf-8")
    (tmp_path / "src/pkg/b.py").write_text("\tbad = 1\n", encoding="utf-8")
    return tmp_path


def test_render_groups_by_file_with_excerpt_underline_and_help(tree):
    diagnostics = [
        Diagnostic("E401", "Multiple imports", "src/pkg/a.py", 2, 8, 6, "split them"),
        Diagnostic("TAB", "tab indent", "src/pkg/b.py", 1, 5, 3, severity="warning"),
        Diagnostic("SIZE", "file too long", "src/pkg/a.py", severity="warning"),
    ]
    assert report.render(diagnostics, footer="run the formatter") == (
        "src/pkg/a.py (2)\n"
        "\n"
        "  SIZE file too long\n"
        "  --> src/pkg/a.py\n"
        "\n"
        "  E401 Multiple imports\n"
        "   --> src/pkg/a.py:2:8\n"
        "    |\n"
        "  2 | import os, sys\n"
        "    |        ^^^^^^\n"
        "    |\n"
        "    = help: split them\n"
        "\n"
        "src/pkg/b.py (1)\n"
        "\n"
        "  TAB tab indent\n"
        "   --> src/pkg/b.py:1:5\n"
        "    |\n"
        "  1 |     bad = 1\n"
        "    |     ^^^\n"
        "\n"
        "Found 1 error and 2 warnings in 2 files.\n"
        "help: run the formatter"
    )


def test_render_color_paints_each_part(tree):
    out = report.render(
        [Diagnostic("E401", "Multiple imports", "src/pkg/a.py", 2, 8, 6, "split")],
        color=True,
    )
    red, blue, cyan, bold, dim, reset = (
        "\x1b[1;31m",
        "\x1b[1;34m",
        "\x1b[1;36m",
        "\x1b[1m",
        "\x1b[2m",
        "\x1b[0m",
    )
    assert out == (
        f"{dim}src/pkg/{reset}{bold}a.py{reset} {dim}(1){reset}\n"
        "\n"
        f"  {red}E401{reset} {bold}Multiple imports{reset}\n"
        f"   {blue}-->{reset} src/pkg/a.py:2:8\n"
        f"    {blue}|{reset}\n"
        f"  {blue}2{reset} {blue}|{reset} import os, sys\n"
        f"    {blue}|{reset} {red}       ^^^^^^{reset}\n"
        f"    {blue}|{reset}\n"
        f"    {blue}={reset} {cyan}help:{reset} split\n"
        "\n"
        f"{red}Found 1 error in 1 file.{reset}"
    )


def test_render_without_diagnostics_is_empty():
    assert report.render([]) == ""


def test_render_skips_the_excerpt_when_the_file_is_unreadable(tmp_path):
    missing = str(tmp_path / "gone.py")
    out = report.render([Diagnostic("X", "boom", missing, 3, 1, 1)])
    assert out == (
        f"{tmp_path}/gone.py (1)\n"
        "\n"
        "  X boom\n"
        f"   --> {missing}:3:1\n"
        "\n"
        "Found 1 error in 1 file."
    )


def test_render_cuts_a_very_long_source_line(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "min.js").write_text("a" * 500 + "\n", encoding="utf-8")
    out = report.render([Diagnostic("X", "huge", "min.js", 1, 1, 1)])
    assert f"1 | {'a' * 159}…" in out


@pytest.mark.parametrize(
    ("env", "tty", "expected"),
    [
        ({}, True, True),
        ({}, False, False),
        ({"NO_COLOR": "1"}, True, False),
        ({"FORCE_COLOR": "1"}, False, True),
        ({"CLICOLOR_FORCE": "1"}, False, True),
        ({"NO_COLOR": "1", "FORCE_COLOR": "1"}, False, False),
        ({"TERM": "dumb"}, True, False),
    ],
)
def test_use_color(env, tty, expected):
    stream = io.StringIO()
    stream.isatty = lambda: tty
    assert report.use_color(stream, env) is expected


def test_display_is_relative_under_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert report.display(tmp_path / "a/b.md") == "a/b.md"
    assert report.display(Path("/elsewhere/c.md")) == "/elsewhere/c.md"


def test_at_underlines_the_needle_case_insensitively_else_the_whole_line(
    tree, monkeypatch
):
    assert report.at("X", "m", "src/pkg/a.py", 2, "SYS") == Diagnostic(
        "X", "m", "src/pkg/a.py", 2, 12, 3
    )
    assert report.at("X", "m", "src/pkg/a.py", 2, "absent") == Diagnostic(
        "X", "m", "src/pkg/a.py", 2, 1, 14
    )


def test_at_accepts_a_pattern(tree):
    assert report.at("X", "m", "src/pkg/a.py", 2, re.compile(r"os,")) == Diagnostic(
        "X", "m", "src/pkg/a.py", 2, 8, 3
    )


def test_a_multiline_help_is_aligned_under_its_first_line(tree):
    out = report.render(
        [Diagnostic("X", "m", "src/pkg/b.py", 1, 1, 1, help="first\nsecond")]
    )
    assert out.splitlines()[-5:-2] == [
        "    |",
        "    = help: first",
        "            second",
    ]
