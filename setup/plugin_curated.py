"""setup/plugin_curated.py — the curated plugin list `install`/`enable` offer when no name is
given: a default shipped with this repo, a user file layered on top (FR-0024-38 to 43).

Two-level model, same shape as `rules.py`'s `RULES_DIR`/`USER_RULES_DIR`: the default ships in
this repo, the user file's `[[entries]]` add or replace (same `marketplace`/`plugin` pair) a
default entry, and its `[[remove]]` drops one. TOML throughout — read via `tomllib` (already used
by `common.py`/`precommit.py`); the user file is the only one ever written back, by hand (FR-0024-43
— no TOML writer dependency, decision 2026-09-23).
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import plugin_catalog
from .common import PACKAGE_DIR

DEFAULT_CURATED_PATH = PACKAGE_DIR / "data" / "curated_plugins.toml"
USER_CURATED_PATH = Path.home() / ".claude" / "pinky-curated-plugins.toml"


@dataclass(frozen=True)
class CuratedEntry:
    """One line of the curated list — a whole marketplace (`plugin` is `None`) or one
    `plugin@marketplace` (FR-0024-38). `source` is transmitted to `claude plugin marketplace add`
    as-is: a GitHub `owner/repo`, a URL, or a workspace-relative directory path (FR-0024-39)."""

    marketplace: str
    source: str
    plugin: str | None = None


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _entries_from(data: dict) -> list[CuratedEntry]:
    return [
        CuratedEntry(
            marketplace=e["marketplace"], source=e["source"], plugin=e.get("plugin")
        )
        for e in data.get("entries", [])
    ]


def _entry_key(marketplace: str, plugin: str | None) -> tuple[str, str | None]:
    return (marketplace, plugin)


def load_curated_entries(user_path: Path | None = None) -> list[CuratedEntry]:
    """The curated list: `DEFAULT_CURATED_PATH` as shipped, `user_path` (default
    `USER_CURATED_PATH`, or `--list`) layered on top — `[[entries]]` there adds a new entry or
    replaces a default one sharing the same `(marketplace, plugin)` key, `[[remove]]` drops a
    default entry by that same key (FR-0024-40, 41, 42). Either file missing or unreadable reads
    as empty, never an error — a fresh machine still gets the default list."""
    default = _entries_from(_load_toml(DEFAULT_CURATED_PATH))
    user_data = _load_toml(user_path or USER_CURATED_PATH)
    removed = {
        _entry_key(r["marketplace"], r.get("plugin"))
        for r in user_data.get("remove", [])
    }
    merged = {_entry_key(e.marketplace, e.plugin): e for e in default}
    for key in removed:
        merged.pop(key, None)
    for entry in _entries_from(user_data):
        merged[_entry_key(entry.marketplace, entry.plugin)] = entry
    return list(merged.values())


def expand_entry(entry: CuratedEntry) -> list[str]:
    """Individual plugin names for one curated entry (FR-0024-36) — the entry's own `plugin` name
    if it names one, or every plugin this machine already knows that marketplace publishes, read
    straight from its local `.claude-plugin/marketplace.json` (no network fetch, no write). A
    marketplace this machine has never registered (a fresh machine, `source` not yet added)
    expands to nothing — the caller shows one unexpanded row for it instead."""
    if entry.plugin is not None:
        return [entry.plugin]
    marketplaces = plugin_catalog._read_json(
        plugin_catalog.CLAUDE_DIR / "plugins" / "known_marketplaces.json"
    )
    known = marketplaces.get(entry.marketplace)
    location = known.get("installLocation") if isinstance(known, dict) else None
    if not location:
        return []
    catalog = plugin_catalog._read_json(
        Path(location) / ".claude-plugin" / "marketplace.json"
    )
    return [
        p["name"]
        for p in catalog.get("plugins", [])
        if isinstance(p, dict) and p.get("name")
    ]


def _toml_string(value: str) -> str:
    """A TOML basic string literal for `value` — `json.dumps` on a plain string produces valid
    TOML (same escaping rules for `\\`, `"`, control characters)."""
    return json.dumps(value, ensure_ascii=False)


def render_curated_toml(entries: list[CuratedEntry]) -> str:
    """The exact text `USER_CURATED_PATH` is written as (FR-0024-43) — every entry as
    `[[entries]]`, `marketplace`/`source` always present, `plugin` only when set."""
    blocks = []
    for e in entries:
        lines = [
            "[[entries]]",
            f"marketplace = {_toml_string(e.marketplace)}",
            f"source = {_toml_string(e.source)}",
        ]
        if e.plugin is not None:
            lines.append(f"plugin = {_toml_string(e.plugin)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
