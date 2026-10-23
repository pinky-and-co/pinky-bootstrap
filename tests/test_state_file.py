"""`setup/state_file.py` — the installer's ledger (décision 7, Entrée 4 de `cli-setup-repo-lot1`).

Records what the installer POSED (path + value), not just a yes/no. On Y->N it must remove only if
the current value is still its own — never touch a value another tool changed since.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.state_file import (
    EntryStatus,
    record_posed,
    status_of,
    unrecord_if_still_mine,
)


@pytest.fixture(autouse=True)
def isolated_state_file(tmp_path, monkeypatch):
    """Every test gets its own state file — never the real `~/.claude/pinky/install-state.json`."""
    import setup.state_file as state_file_module

    monkeypatch.setattr(state_file_module, "STATE_FILE_PATH", tmp_path / "state.json")
    return tmp_path / "state.json"


def test_absent_when_current_reader_returns_none():
    assert status_of("statusLine", current_reader=lambda: None) == EntryStatus.ABSENT


def test_present_not_mine_when_never_posed():
    # Something is there on disk, but we never recorded posing it.
    assert (
        status_of("statusLine", current_reader=lambda: "/some/other/path.py")
        == EntryStatus.PRESENT_NOT_MINE
    )


def test_posed_by_me_when_current_value_matches_recorded():
    record_posed(
        "statusLine",
        path="~/.claude/settings.json",
        value="/pinky/statusline.py",
    )
    assert (
        status_of("statusLine", current_reader=lambda: "/pinky/statusline.py")
        == EntryStatus.POSED_BY_ME
    )


def test_present_not_mine_when_current_value_diverged_from_recorded():
    # We posed X, but the current value is Y — someone else touched it since.
    record_posed(
        "statusLine",
        path="~/.claude/settings.json",
        value="/pinky/statusline.py",
    )
    assert (
        status_of("statusLine", current_reader=lambda: "/someone/else.py")
        == EntryStatus.PRESENT_NOT_MINE
    )


def test_record_posed_persists_across_reloads(isolated_state_file):
    record_posed(
        "statusLine",
        path="~/.claude/settings.json",
        value="/pinky/statusline.py",
    )
    raw = json.loads(isolated_state_file.read_text(encoding="utf-8"))
    assert raw["statusLine"]["value"] == "/pinky/statusline.py"


def test_unrecord_removes_when_still_mine():
    record_posed(
        "statusLine",
        path="~/.claude/settings.json",
        value="/pinky/statusline.py",
    )
    removed_calls = []
    removed = unrecord_if_still_mine(
        "statusLine",
        current_reader=lambda: "/pinky/statusline.py",  # unchanged since we posed it
        remover=lambda: removed_calls.append(True),
    )
    assert removed is True
    assert removed_calls == [True]
    assert status_of("statusLine", current_reader=lambda: None) == EntryStatus.ABSENT


def test_unrecord_leaves_value_alone_when_no_longer_mine():
    record_posed(
        "statusLine",
        path="~/.claude/settings.json",
        value="/pinky/statusline.py",
    )
    removed_calls = []
    removed = unrecord_if_still_mine(
        "statusLine",
        current_reader=lambda: (
            "/someone/else.py"
        ),  # diverged — another tool passed since
        remover=lambda: removed_calls.append(True),
    )
    assert removed is False
    assert removed_calls == []  # remover must never be called


def test_unrecord_is_a_noop_when_absent():
    removed_calls = []
    removed = unrecord_if_still_mine(
        "statusLine",
        current_reader=lambda: None,
        remover=lambda: removed_calls.append(True),
    )
    assert removed is False
    assert removed_calls == []
