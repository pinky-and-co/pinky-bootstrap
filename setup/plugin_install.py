"""setup/plugin_install.py — fetch a plugin's files, then wire what a plugin manifest can't carry.

`claude plugin install` (Claude Code's own command) fetches a plugin into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and enables it. One thing it does not
do that this workspace needs: the main-session `statusLine` key is not readable from a plugin's
bundled `settings.json` — Claude Code reads only `agent` and `subagentStatusLine` there (verified
2026-08-28) — so a plugin that ships a status line still needs an explicit `statusLine` entry
pointing at its installed script.

That entry is an absolute path with the plugin version in it, so `set_status_lines` re-resolves it
from the install registry (never a guessed path) on every `pinky install` run — the
replayable-converger model. Re-run after `claude plugin update <plugin>`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import state_file

_REGISTRY = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
_USER_SETTINGS = Path.home() / ".claude" / "settings.json"


def install_plugin_files(plugin_id: str, marketplace: str | None = None) -> None:
    """Shell out to `claude plugin install` — fetch + enable at user scope — then `update`, so a
    re-run picks up a changed plugin (both are `restart required to apply`, like the rest of D2).

    `check=True` on install: a failure there must stop the flow, never leave the caller wiring
    settings for a plugin whose files never landed. `update` is best-effort (it errors when the
    plugin is brand-new and already current).
    """
    spec = f"{plugin_id}@{marketplace}" if marketplace else plugin_id
    subprocess.run(
        ["claude", "plugin", "install", spec, "--scope", "user", "--yes"],
        check=True,
    )
    subprocess.run(["claude", "plugin", "update", spec], check=False)


def resolve_install_path(plugin_id: str, marketplace: str | None = None) -> Path:
    """The directory `claude plugin install` unpacked the plugin into, from the registry it keeps
    (`installed_plugins.json`) — authoritative, and still correct after a version bump."""
    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    plugins = data.get("plugins", {})
    keys = (
        [f"{plugin_id}@{marketplace}"]
        if marketplace
        else [k for k in plugins if k.split("@", 1)[0] == plugin_id]
    )
    for key in keys:
        for entry in plugins.get(key, []):
            path = Path(entry["installPath"])
            if path.is_dir():
                return path
    raise FileNotFoundError(
        f"{plugin_id!r} not in {_REGISTRY} — was `claude plugin install` run?"
    )


def _merge_user_settings(updates: dict[str, object]) -> None:
    """Merge `updates` into `~/.claude/settings.json` — read what's there, set only these keys,
    same discipline as `plugin_scope.enable_plugin` and `agentic_assets._install`."""
    data = (
        json.loads(_USER_SETTINGS.read_text(encoding="utf-8"))
        if _USER_SETTINGS.is_file()
        else {}
    )
    data.update(updates)
    _USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _USER_SETTINGS.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def set_status_lines(install_path: Path) -> list[str]:
    """If `install_path` ships `scripts/statusline.py`, point `statusLine` (and
    `subagentStatusLine` when the script is there too) at the installed scripts, merged into
    `~/.claude/settings.json`. Returns the keys written — empty when the plugin has no status line.

    `subagentStatusLine` is also declared in the plugin's own bundled `settings.json`; writing it
    here as well is deliberate until `${CLAUDE_PLUGIN_ROOT}` expansion inside a bundled
    `settings.json` is confirmed working (a user `settings.json` value wins over a plugin one).
    """
    main = install_path / "scripts" / "statusline.py"
    if not main.is_file():
        return []

    sub = install_path / "scripts" / "subagent_statusline.py"
    scripts = {"statusLine": main}
    if sub.is_file():
        scripts["subagentStatusLine"] = sub

    _merge_user_settings(
        {
            key: {"type": "command", "command": f'python3 "{path}"'}
            for key, path in scripts.items()
        }
    )
    for key, path in scripts.items():
        state_file.record_posed(key, path=str(_USER_SETTINGS), value=str(path))
    return list(scripts)
