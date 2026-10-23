"""setup/user_state.py — every file the `pinky` CLI owns lives under `~/.claude/pinky/`.

One directory to remove at uninstall, and a future file cannot be forgotten on a list: the
install ledger (`install-state.json`), the user's curated list (`curated-plugins.toml`), and
the plugin-scope state the plugins' hooks share with the CLI (`plugin-scope/`).

`migrate()` runs at CLI startup. The pre-`pinky/` location of each of the three is a flat
`~/.claude/` sibling named `pinky-` + its current name — a file there whose `pinky/` form does
not exist moves by rename (identical bytes); the scope-state directory is deleted instead of
moved (best-effort, a symlink is unlinked and not followed), its per-session files never outlive
a session anyway — even when `pinky/plugin-scope` exists. A file (not the scope directory) whose
`pinky/` form exists is left alone, both stay.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import plugin_curated, state_file

PLUGIN_SCOPE_DIR = Path.home() / ".claude" / "pinky" / "plugin-scope"

_LEGACY_NAME_PREFIX = "pinky-"


def _legacy_path(current: Path) -> Path:
    """The same path's pre-`pinky/` form: a `pinky-`-prefixed sibling of the directory."""
    return current.parent.parent / (_LEGACY_NAME_PREFIX + current.name)


def migrate() -> None:
    """Move the ledger and the curated list under `~/.claude/pinky/` once, drop the legacy
    scope-state directory. Idempotent — a run that finds nothing writes nothing.

    Best-effort: an `OSError` (read-only home, `~/.claude/pinky` existing as a file...) is
    ignored so the CLI never fails on it; the next start retries.
    """
    for current in (state_file.STATE_FILE_PATH, plugin_curated.USER_CURATED_PATH):
        try:
            old = _legacy_path(current)
            if old.is_file() and not current.exists():
                current.parent.mkdir(parents=True, exist_ok=True)
                old.replace(current)
        except OSError:
            pass
    try:
        legacy_scope = _legacy_path(PLUGIN_SCOPE_DIR)
        if legacy_scope.is_symlink():
            legacy_scope.unlink()
        elif legacy_scope.is_dir():
            shutil.rmtree(legacy_scope, ignore_errors=True)
    except OSError:
        pass
