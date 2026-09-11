"""setup.llm_drift — drift kinds, the comments fixer, and the per-read token savings it reports."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import llm_drift

SRC = (
    "import os  # noqa: F401\n"
    "\n"
    "# decided 2026-07-24\n"
    "x = 1  # why\n"
    "# a\n"
    "# b\n"
    "# c\n"
    "# d\n"
    "y = 2\n"
)
STRIPPED = "import os  # noqa: F401\n\nx = 1\ny = 2\n"


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    return repo


def test_strip_comments_keeps_directives_and_the_program():
    assert llm_drift.strip_comments(SRC) == STRIPPED


def test_strip_comments_never_touches_a_hash_inside_a_string():
    src = (
        '"""Doc.\n\n    pip install x   # extras\n"""\n'
        'fmt = "#,##0.00"\n'
        'color = f"#{hex_}"\n'
    )
    assert llm_drift.strip_comments(src) == src


def test_strip_comments_keeps_shebang_and_pep723():
    src = (
        "#!/usr/bin/env python3\n"
        "# /// script\n"
        '# dependencies = ["mcp"]\n'
        "# ///\n"
        "rows: list[dict] = []  # type: ignore[type-arg]\n"
    )
    assert llm_drift.strip_comments(src) == src


def test_weigh_counts_lines_comments_and_chars():
    assert llm_drift.weigh(SRC) == llm_drift.Weight(
        lines=8, comment_lines=5, chars=len(SRC)
    )


def test_scan_reports_every_kind_by_line(tmp_path):
    repo = _repo(tmp_path, {"mod.py": SRC, "bad.py": "def (:\n"})
    scan = llm_drift.scan_repo(repo, ["comments", "narrative", "long-comment"])
    assert llm_drift.format_scan(scan) == [
        "== demo · 1 .py · 62.5 % comment lines · ≈21 tokens",
        "  mod.py:3  comments  # decided 2026-07-24",
        "  mod.py:3  narrative  # decided 2026-07-24",
        "  mod.py:4  comments  # why",
        "  mod.py:5  comments  # a",
        "  mod.py:5  long-comment  # a",
        "  mod.py:6  comments  # b",
        "  mod.py:7  comments  # c",
        "  mod.py:8  comments  # d",
        "  skipped (does not parse): bad.py",
        "  comments 6 · narrative 1 · long-comment 1",
    ]


def test_scan_json_is_a_snapshot(tmp_path):
    repo = _repo(tmp_path, {"mod.py": SRC})
    scan = llm_drift.scan_repo(repo, ["narrative"])
    assert json.loads(llm_drift.scans_to_json([scan])) == [
        {
            "repo": "demo",
            "files": 1,
            "lines": 8,
            "comment_lines": 5,
            "chars": 81,
            "tokens": 21,
            "findings": [
                {
                    "path": "mod.py",
                    "line": 3,
                    "kind": "narrative",
                    "text": "# decided 2026-07-24",
                }
            ],
            "skipped": [],
        }
    ]


def test_fix_dry_run_writes_nothing_and_reports_the_savings(tmp_path):
    repo = _repo(tmp_path, {"mod.py": SRC})
    fix = llm_drift.fix_repo(repo, "comments", dry_run=True)
    assert (repo / "mod.py").read_text(encoding="utf-8") == SRC
    assert llm_drift.format_fix(fix, dry_run=True) == (
        "demo · 1 file · −5 lines · ≈−11 tokens per read (−52.4 % of the repo)"
        " · dry-run, nothing written"
    )


def test_fix_rewrites_the_file_and_skips_what_does_not_parse(tmp_path):
    repo = _repo(tmp_path, {"mod.py": SRC, "bad.py": "def (:\n"})
    fix = llm_drift.fix_repo(repo, "comments", dry_run=False, reformat=False)
    assert (repo / "mod.py").read_text(encoding="utf-8") == STRIPPED
    assert (repo / "bad.py").read_text(encoding="utf-8") == "def (:\n"
    assert fix.changed == [Path("mod.py")]
    assert fix.skipped == [Path("bad.py")]


def test_fix_refuses_a_kind_without_fixer(tmp_path):
    repo = _repo(tmp_path, {"mod.py": SRC})
    with pytest.raises(ValueError, match="no fixer"):
        llm_drift.fix_repo(repo, "narrative", dry_run=True)


def test_ruff_version_reads_the_python_extra(tmp_path, monkeypatch):
    extras = tmp_path / "extras"
    extras.mkdir()
    (extras / "python.yaml").write_text(
        "  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v9.8.7\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_drift, "CORE_PRECOMMIT_DIR", tmp_path)
    assert llm_drift.ruff_version() == "9.8.7"


def test_setup_cli_routes_llm_drift_to_run(monkeypatch):
    from setup import cli

    calls = []
    monkeypatch.setattr(
        llm_drift, "select_repos", lambda name, every: [Path("/r")] if every else []
    )
    monkeypatch.setattr(
        llm_drift,
        "run",
        lambda action, repos, kinds, *, dry_run, as_json: (
            calls.append((action, repos, kinds, dry_run, as_json)) or 0
        ),
    )
    with pytest.raises(SystemExit) as exc:
        cli.main(["--llm-drift", "scan", "--all", "--kind", "narrative", "--json"])
    assert exc.value.code == 0
    assert calls == [("scan", [Path("/r")], ["narrative"], False, True)]


def test_run_without_a_repo_is_an_error(capsys):
    assert llm_drift.run("scan", [], [], dry_run=False, as_json=False) == 1
    assert capsys.readouterr().out == (
        "llm-drift: no repo — pass --repo NAME or --all, or run it inside a repo\n"
    )
