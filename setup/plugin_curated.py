"""setup/plugin_curated.py — the curated plugin list `install`/`enable` offer when no name is
given: a default shipped with this repo, a user file layered on top.

Two-level model, same shape as `rules.py`'s `RULES_DIR`/`USER_RULES_DIR`: the default ships in
this repo, the user file's `[[entries]]` add or replace (same `marketplace`/`plugin` pair) a
default entry, and its `[[remove]]` drops one. TOML throughout — read via `tomllib` (already used
elsewhere); the user file is the only one ever written back, serialized by hand — no TOML
writer dependency.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from . import plugin_catalog, tui
from .common import PACKAGE_DIR

DEFAULT_CURATED_PATH = PACKAGE_DIR / "data" / "curated_plugins.toml"
USER_CURATED_PATH = Path.home() / ".claude" / "pinky-curated-plugins.toml"
# A picker row standing in for a whole-marketplace entry this machine has never registered —
# not a real plugin name, so `expand_entry` never produces one; only
# `resolve_no_name_selection`'s own row-building and recognition ever touch this marker.
UNREGISTERED_MARKER = "@"


@dataclass(frozen=True)
class CuratedEntry:
    """One line of the curated list — a whole marketplace (`plugin` is `None`) or one
    `plugin@marketplace`. `source` is transmitted to `claude plugin marketplace add`
    as-is: a GitHub `owner/repo`, a URL, or a workspace-relative directory path."""

    marketplace: str
    source: str
    plugin: str | None = None


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _load_toml_strict(path: Path) -> dict:
    """Like `_load_toml`, but a syntactically broken (not merely absent) file raises —
    `sync_user_file` must never treat "I couldn't parse this" the same as "there was nothing
    here" and silently overwrite the user's own content with just the new entries."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return tomllib.loads(text)


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
    default entry by that same key. Either file missing or unreadable reads
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


def _known_marketplaces() -> dict:
    return plugin_catalog._read_json(
        plugin_catalog.CLAUDE_DIR / "plugins" / "known_marketplaces.json"
    )


def is_registered(entry: CuratedEntry) -> bool:
    """Whether this machine already has `claude plugin marketplace add`ed `entry.marketplace` —
    the split between `expand_entry` reading its catalog locally and the picker showing one
    unexpanded row instead."""
    return isinstance(_known_marketplaces().get(entry.marketplace), dict)


def expand_entry(entry: CuratedEntry) -> list[str]:
    """Individual plugin names for one curated entry — the entry's own `plugin` name
    if it names one, or every plugin this machine already knows that marketplace publishes, read
    straight from its local `.claude-plugin/marketplace.json` (no network fetch, no write). A
    marketplace this machine has never registered (a fresh machine, `source` not yet added)
    expands to nothing — the caller shows one unexpanded row for it instead."""
    if entry.plugin is not None:
        return [entry.plugin]
    known = _known_marketplaces().get(entry.marketplace)
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


def resolve_source(source: str, workspace_root: Path) -> str:
    """`source` for `claude plugin marketplace add` — a relative filesystem path that
    actually exists under `workspace_root` resolves to its absolute form; a GitHub `owner/repo` or
    a URL (nothing on disk at that path) passes through unchanged. The two look identical as bare
    strings, so existence on disk is the only signal that tells them apart."""
    candidate = Path(source)
    if not candidate.is_absolute():
        candidate = workspace_root / source
    return str(candidate) if candidate.is_dir() else source


def add_marketplace(entry: CuratedEntry, workspace_root: Path) -> None:
    """`claude plugin marketplace add <source>` for a whole-marketplace entry this machine has
    never registered. `check=True`: the caller must not treat this as done, or expand
    it, or offer to remember it, if the add itself failed."""
    subprocess.run(
        [
            "claude",
            "plugin",
            "marketplace",
            "add",
            resolve_source(entry.source, workspace_root),
        ],
        check=True,
    )


def _toml_string(value: str) -> str:
    """A TOML basic string literal for `value` — `json.dumps` on a plain string produces valid
    TOML (same escaping rules for `\\`, `"`, control characters)."""
    return json.dumps(value, ensure_ascii=False)


def render_curated_toml(
    entries: list[CuratedEntry], removes: list[dict] | None = None
) -> str:
    """The exact text `USER_CURATED_PATH` is written as: every entry as
    `[[entries]]`, `marketplace`/`source` always present, `plugin` only when set. `removes`: raw
    `[[remove]]` tables read back from the file being rewritten, preserved as-is — `sync_user_file`
    must never drop a removal directive it did not itself add or change."""
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
    for r in removes or []:
        lines = ["[[remove]]", f"marketplace = {_toml_string(r['marketplace'])}"]
        if r.get("plugin"):
            lines.append(f"plugin = {_toml_string(r['plugin'])}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def sync_user_file(
    new_entries: list[CuratedEntry],
    user_path: Path | None = None,
    *,
    yes: bool = False,
) -> bool:
    """`new_entries` this run just used (typically freshly `claude plugin marketplace
    add`ed) that are not yet in the user's curated file — show the diff, ask `[y/N]`,
    append and write if confirmed. A no-op, nothing printed, when every one of `new_entries` is
    already there. Returns whether anything was written. Refuses (prints why, writes nothing) when
    the file exists but fails to parse — never silently replaces content it could not read."""
    path = user_path or USER_CURATED_PATH
    try:
        user_data = _load_toml_strict(path)
    except tomllib.TOMLDecodeError as exc:
        print(
            f"{path} is not valid TOML — refusing to overwrite it: {exc}",
            file=sys.stderr,
        )
        return False
    current = _entries_from(user_data)
    removes = user_data.get("remove", [])
    current_keys = {_entry_key(e.marketplace, e.plugin) for e in current}
    to_add = [
        e
        for e in new_entries
        if _entry_key(e.marketplace, e.plugin) not in current_keys
    ]
    if not to_add:
        return False
    print(f"New marketplace(s) to remember in {path}:")
    for e in to_add:
        print(f"  + {e.marketplace} ({e.source})")
    if not yes and input("Save? [y/N] ").strip().lower() != "y":
        print("left unsaved.")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_curated_toml(current + to_add, removes), encoding="utf-8")
    print(f"saved → {path}")
    return True


def resolve_no_name_selection(
    workspace_root: Path,
    installed_names: Iterable[str],
    *,
    user_path: Path | None = None,
    yes: bool = False,
    dry_run: bool = False,
    picker: Callable[..., list[bool]] | None = None,
) -> list[str]:
    """`install`/`enable` with no plugin name, end to end: the
    curated ∪ installed picker, a registered marketplace expanded to its plugins, an unregistered
    one offered as a single row — check it, confirm, `claude plugin marketplace add` it, expand it
    now that it is registered, and offer to remember it in the user file. Returns only the newly
    picked names — an already-installed one that stays checked
    has nothing new to place, so it never reopens its own target table here; `install <name>` (or
    `enable <name>`) named directly still does. `dry_run`: neither `marketplace add` nor the user
    file write ever run — a checked unregistered row is reported, not added."""
    from . import (
        plugin_enable,
    )  # local: plugin_enable never imports this module, no cycle

    installed = set(installed_names)
    entries = load_curated_entries(user_path)
    curated_names: set[str] = set()
    # Grouped by marketplace, not by entry: two entries (a `plugin=` one and a whole-marketplace
    # one, or two different `plugin=` ones) can share one not-yet-registered marketplace, and
    # `marketplace add` must run once for the group, not once per entry.
    marker_to_entries: dict[str, list[CuratedEntry]] = {}
    for entry in entries:
        if is_registered(entry):
            curated_names.update(expand_entry(entry))
        else:
            marker = f"{UNREGISTERED_MARKER}{entry.marketplace}"
            marker_to_entries.setdefault(marker, []).append(entry)
            curated_names.add(marker)

    picked = plugin_enable.pick_plugins(
        sorted(curated_names), sorted(installed), picker=picker or tui.run_checklist
    )
    markers = [n for n in picked if n in marker_to_entries]
    names = [n for n in picked if n not in marker_to_entries and n not in installed]
    if not markers:
        return names

    unregistered = [marker_to_entries[m][0] for m in markers]
    if dry_run:
        print(
            "would add marketplace(s): "
            f"{', '.join(e.marketplace for e in unregistered)} — dry run"
        )
        return names

    prompt = (
        "Also add marketplace(s): "
        f"{', '.join(e.marketplace for e in unregistered)}? [y/N] "
    )
    confirmed = yes or (sys.stdin.isatty() and input(prompt).strip().lower() == "y")
    if not confirmed:
        print(f"left out: {', '.join(e.marketplace for e in unregistered)}")
        return names

    added = []
    for marker, first_entry in zip(markers, unregistered, strict=True):
        try:
            add_marketplace(first_entry, workspace_root)
        except subprocess.CalledProcessError as exc:
            print(
                f"failed to add marketplace {first_entry.marketplace}: {exc}",
                file=sys.stderr,
            )
            continue
        for entry in marker_to_entries[marker]:
            added.append(entry)
            names.extend(expand_entry(entry))
    if added:
        sync_user_file(added, user_path, yes=yes)
    return names
