"""check_requirement_ids.py — blocks any requirement id, in any text file, anywhere in the file."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "check_requirement_ids.py"

_spec = importlib.util.spec_from_file_location("check_requirement_ids", HOOK)
cri = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cri)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def test_finds_ids_in_code_strings_comments_and_prose(tmp_path):
    f = _write(
        tmp_path,
        "mix.py",
        'x = 1\nhelp="omit: the list, FR-0024-33"\n# see NFR-0024-37\nfine = "FR-2024"\n',
    )
    assert cri.find_ids(f) == [(2, "FR-0024-33"), (3, "NFR-0024-37")]


def test_finds_ids_in_markdown_and_shell(tmp_path):
    md = _write(tmp_path, "doc.md", "Covers ASS-0025-68 and IMP-0024-30.\n")
    sh = _write(tmp_path, "run.sh", "echo ok  # LEG-0001-2\n")
    assert cri.find_ids(md) == [(1, "ASS-0025-68"), (1, "IMP-0024-30")]
    assert cri.find_ids(sh) == [(1, "LEG-0001-2")]


def test_unreadable_or_binary_file_has_no_findings(tmp_path):
    f = tmp_path / "blob.bin"
    f.write_bytes(b"\xff\xfe\x00FR-0024-1")
    assert cri.find_ids(f) == []


def test_main_blocks_and_prints_every_finding(tmp_path, monkeypatch, capsys):
    f = _write(tmp_path, "a.py", '"""Does X (FR-0024-51)."""\n')
    monkeypatch.setattr(sys, "argv", ["hook", str(f)])
    monkeypatch.delenv("PINKY_DISABLED_HOOKS", raising=False)

    assert cri.main() == 1
    assert capsys.readouterr().out == (
        f"❌ [REQ-ID] {f}:1: FR-0024-51\n"
        "   💡 1 requirement id(s) — the spec they point to lives outside the repo and is pruned "
        "after implementation: delete the id, state the behaviour.\n"
    )


def test_main_passes_on_clean_files(tmp_path, monkeypatch, capsys):
    f = _write(tmp_path, "a.py", "x = 1\n")
    monkeypatch.setattr(sys, "argv", ["hook", str(f)])

    assert cri.main() == 0
    assert capsys.readouterr().out == ""


def test_disabled_hook_passes(tmp_path, monkeypatch):
    f = _write(tmp_path, "a.py", "# FR-0024-1\n")
    monkeypatch.setattr(sys, "argv", ["hook", str(f)])
    monkeypatch.setenv("PINKY_DISABLED_HOOKS", "check_requirement_ids")

    assert cri.main() == 0
