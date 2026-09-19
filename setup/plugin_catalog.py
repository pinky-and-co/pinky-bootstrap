"""setup/plugin_catalog.py — the plugin and marketplace names Claude Code knows on this machine.

Read for shell completion: `pinky claude-plugin install <TAB>` offers the plugins already installed
(`installed_plugins.json`) and every plugin a known marketplace publishes, so one that is not
installed yet completes too. Everything is best-effort: a missing or malformed file completes
nothing, never fails a keystroke.
"""

from __future__ import annotations

import json
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def known_marketplace_names() -> list[str]:
    """Every marketplace registered with Claude Code, sorted."""
    return sorted(_read_json(CLAUDE_DIR / "plugins" / "known_marketplaces.json"))


def known_plugin_names() -> list[str]:
    """Bare plugin names, installed or published by a known marketplace, sorted and unique."""
    names = {
        key.split("@", 1)[0]
        for key in _read_json(CLAUDE_DIR / "plugins" / "installed_plugins.json").get(
            "plugins", {}
        )
    }
    marketplaces = _read_json(CLAUDE_DIR / "plugins" / "known_marketplaces.json")
    for entry in marketplaces.values():
        location = entry.get("installLocation") if isinstance(entry, dict) else None
        if not location:
            continue
        catalog = _read_json(Path(location) / ".claude-plugin" / "marketplace.json")
        names.update(
            plugin["name"]
            for plugin in catalog.get("plugins", [])
            if isinstance(plugin, dict) and plugin.get("name")
        )
    return sorted(names)
