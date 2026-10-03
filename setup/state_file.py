"""setup/state_file.py — pinky's install ledger: what it POSED, so a later run knows what it
owns.

Records not just Y/N but the path and value written for each entry. On Y->N, removal happens only
if the current value is still what we posed — if another tool changed it since, we leave it alone
and report that, rather than clobbering a value we no longer own.

Each caller (statusline install, marketplace registration, ...) knows how to read/remove its own
target — this module never guesses a target's shape, it only keeps the ledger.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

STATE_FILE_PATH = Path.home() / ".claude" / "pinky-install-state.json"


class EntryStatus(StrEnum):
    """Where one entry stands relative to what we last posed."""

    POSED_BY_ME = "posed_by_me"
    PRESENT_NOT_MINE = "present_not_mine"
    ABSENT = "absent"


@dataclass
class PosedEntry:
    """One thing the installer wrote: what it wrote (`value`) and where (`path`)."""

    key: str
    path: str
    value: str


def _load_entries() -> dict[str, PosedEntry]:
    """Every entry the installer has posed, keyed by `key`. Empty dict if never run."""
    if not STATE_FILE_PATH.is_file():
        return {}
    raw = json.loads(STATE_FILE_PATH.read_text(encoding="utf-8"))
    return {key: PosedEntry(**fields) for key, fields in raw.items()}


def _save_entries(entries: dict[str, PosedEntry]) -> None:
    STATE_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        key: {"key": entry.key, "path": entry.path, "value": entry.value}
        for key, entry in entries.items()
    }
    STATE_FILE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def record_posed(key: str, path: str, value: str) -> None:
    """Record that the installer just wrote `value` at `path` for `key`.

    Call right after the actual write — this only updates the ledger, it never writes the target
    itself.
    """
    entries = _load_entries()
    entries[key] = PosedEntry(key=key, path=path, value=value)
    _save_entries(entries)


def posed_value(key: str) -> str | None:
    """The value the installer last recorded for `key`, or None if it never posed one. Lets a
    replayable command (`pinky claude-plugin reconcile`) read back its own prior decision."""
    entry = _load_entries().get(key)
    return entry.value if entry else None


def status_of(key: str, current_reader: Callable[[], str | None]) -> EntryStatus:
    """Resolve one entry's status against the ledger.

    `current_reader` reads the CURRENT value on disk for `key` (or None if absent) — the caller
    knows how to read its own target (a settings.json key, a file's existence, ...), this module
    doesn't guess.
    """
    current = current_reader()
    if current is None:
        return EntryStatus.ABSENT
    entries = _load_entries()
    posed = entries.get(key)
    if posed is not None and posed.value == current:
        return EntryStatus.POSED_BY_ME
    return EntryStatus.PRESENT_NOT_MINE


def unrecord_if_still_mine(
    key: str,
    current_reader: Callable[[], str | None],
    remover: Callable[[], None],
) -> bool:
    """On Y->N: remove the target only if the current value is still what we posed.

    `remover` actually deletes/reverts the target — called only when safe (status is
    POSED_BY_ME). Never touches anything if another tool changed the value since: that is the
    whole point of tracking what we posed instead of a bare boolean. Returns True if removed.
    """
    if status_of(key, current_reader) != EntryStatus.POSED_BY_ME:
        return False
    remover()
    entries = _load_entries()
    del entries[key]
    _save_entries(entries)
    return True
