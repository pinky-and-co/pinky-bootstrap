"""check_latex_notation.py — blocking detector of raw LaTeX instead of a Unicode symbol."""

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "check_latex_notation.py"

_spec = importlib.util.spec_from_file_location("check_latex_notation", HOOK)
cln = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cln)


def _write(src: str, tmp_path: Path) -> Path:
    f = tmp_path / "sample.md"
    f.write_text(src, encoding="utf-8")
    return f


def test_dollar_delimited_command_is_flagged(tmp_path):
    f = _write("A `SAINT` $\\rightarrow$ `ST`.\n", tmp_path)
    assert cln.check_file(str(f)) == [1]


def test_bare_command_without_dollars_is_clean(tmp_path):
    """Both dollar signs are required — a bare command matches too much (regex examples,
    Windows paths, this checker's own LATEX_TO_UNICODE table) for near-zero real payoff:
    every real occurrence observed so far carried both delimiters."""
    f = _write("Cible \\rightarrow Push\n", tmp_path)
    assert cln.check_file(str(f)) == []


def test_checker_does_not_flag_its_own_source():
    assert cln.check_file(str(HOOK)) == []


def test_unicode_arrow_is_clean(tmp_path):
    f = _write("A `SAINT` → `ST`.\n", tmp_path)
    assert cln.check_file(str(f)) == []


def test_multiple_commands_on_distinct_lines(tmp_path):
    f = _write(
        "line one $\\times$ two\nline clean\nline three $\\alpha$ four\n",
        tmp_path,
    )
    assert cln.check_file(str(f)) == [1, 3]


def test_fenced_code_block_is_skipped(tmp_path):
    f = _write(
        "Some prose.\n"
        "```\n"
        "the bug looks like $\\rightarrow$ in a commit\n"
        "```\n"
        "More prose $\\pi$ here.\n",
        tmp_path,
    )
    assert cln.check_file(str(f)) == [5]


def test_tilde_fence_is_also_skipped(tmp_path):
    f = _write(
        "~~~\n$\\rightarrow$\n~~~\n",
        tmp_path,
    )
    assert cln.check_file(str(f)) == []


def test_binary_file_is_skipped(tmp_path):
    f = tmp_path / "sample.bin"
    f.write_bytes(b"\x00\x01$\\rightarrow$")
    assert cln.check_file(str(f)) == []


def test_disabled_via_env_returns_success(tmp_path, monkeypatch):
    f = _write("$\\rightarrow$\n", tmp_path)
    monkeypatch.setenv("PINKY_DISABLED_HOOKS", "check_latex_notation")
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0
    assert run.stdout == ""


def test_findings_print_path_line_and_fail(tmp_path):
    f = _write("$\\rightarrow$\n", tmp_path)
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 1
    assert run.stdout == (
        f"{f} (1)\n"
        "\n"
        "  LATEX raw LaTeX notation instead of a Unicode symbol\n"
        f"   --> {f}:1:1\n"
        "    |\n"
        "  1 | $\\rightarrow$\n"
        "    | ^^^^^^^^^^^^^\n"
        "    |\n"
        "    = help: replace the command with its Unicode character (e.g. `\\rightarrow` → `→`)\n"
        "\n"
        "Found 1 error in 1 file.\n"
        "help: likely source: a local LLM (Gemma/Ollama) falling back to its training notation "
        "on long, freely-composed text\n"
    )


def test_clean_file_returns_success(tmp_path):
    f = _write("nothing suspicious here\n", tmp_path)
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0
    assert run.stdout == ""
