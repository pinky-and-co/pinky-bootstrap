"""setup/plugin_reconcile.py — audit where every known plugin is actually enabled.

`pinky plugins reconcile` needs the real picture before it can ask the user to fix it. Two
registries, deliberately not merged (measured 2026-09-02):

- **`enabledPlugins`** in every `.claude/settings.json` / `.claude/settings.local.json` — where a
  plugin is *activated*. `~/.claude/settings.json` is the user scope; a file at a workspace
  directory (root, a group like `pinky-lib/`, a nested repo) is that directory's scope.
- **`installed_plugins.json`** — where a plugin's *files* were fetched, per `scope`. A plugin can
  be here (`pyright-lsp`, `scope: local`) without an `enabledPlugins: true` key anywhere, and a
  key can exist (`@inline`) with nothing in this registry.

`audit_plugins` walks both and returns one `PluginState` per plugin id — the input to the report
(bare `reconcile`) and to the interactive `--apply` loop.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import plugin_install, state_file
from .plugin_scope import list_targets_at_depth, run_marketplace_wizard

_USER_CLAUDE = Path.home() / ".claude"
_REGISTRY = _USER_CLAUDE / "plugins" / "installed_plugins.json"


@dataclass(frozen=True)
class PluginState:
    """Everything the reconcile flow needs to know about one plugin, by its ``<id>@<marketplace>``
    key. ``enabled_at`` / ``disabled_at`` / ``installed_scopes`` are sorted, duplicate-free."""

    plugin_id: str
    marketplace: str
    enabled_at: tuple[str, ...]
    disabled_at: tuple[str, ...]
    installed_scopes: tuple[str, ...]
    ships_status_line: bool

    @property
    def is_user_enabled(self) -> bool:
        return "user" in self.enabled_at

    @property
    def is_ghost(self) -> bool:
        """Known to the machine but activated nowhere — a candidate for uninstall."""
        return not self.enabled_at


def _scope_label(directory: Path, workspace_root: Path) -> str:
    """A short label for a settings.json location: ``.`` for the workspace root, otherwise the
    path relative to it (``pinky-lib``, ``pinky-lib/pinky-core``).

    Always ``/``-separated (``as_posix``) — the label is a stable identifier (audit output,
    ledger decision keys), never an OS path, so it must not vary between POSIX and Windows.
    """
    if directory == workspace_root:
        return "."
    try:
        return directory.relative_to(workspace_root).as_posix()
    except ValueError:
        return directory.as_posix()


def _settings_locations(workspace_root: Path) -> list[tuple[str, Path]]:
    """``(label, settings-file)`` for every scope a plugin can be enabled at, user scope first.

    Each workspace directory contributes both its ``settings.json`` and its ``settings.local.json``
    (the second labelled ``<label> (local)``). Missing files are kept in the list — the reader
    skips them — so the set of scopes is stable regardless of what exists yet.
    """
    dirs = [workspace_root]
    for depth in (1, 2):
        dirs += list_targets_at_depth(workspace_root, depth)

    locations: list[tuple[str, Path]] = [("user", _USER_CLAUDE / "settings.json")]
    for directory in dirs:
        label = _scope_label(directory, workspace_root)
        locations.append((label, directory / ".claude" / "settings.json"))
        locations.append(
            (f"{label} (local)", directory / ".claude" / "settings.local.json")
        )
    return locations


def _read_enabled_plugins(settings_file: Path) -> dict[str, bool]:
    """The ``enabledPlugins`` map of one settings file — ``{}`` if the file is absent or malformed
    (a broken settings.json at one scope must not blind the audit to the others)."""
    if not settings_file.is_file():
        return {}
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    enabled = data.get("enabledPlugins", {})
    return {k: v for k, v in enabled.items() if isinstance(v, bool)}


def _read_registry() -> dict[str, list[dict]]:
    if not _REGISTRY.is_file():
        return {}
    try:
        return json.loads(_REGISTRY.read_text(encoding="utf-8")).get("plugins", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _install_path_for(entries: list[dict]) -> Path | None:
    for entry in entries:
        path = entry.get("installPath")
        if path and Path(path).is_dir():
            return Path(path)
    return None


def audit_plugins(workspace_root: Path) -> dict[str, PluginState]:
    """One `PluginState` per plugin id found in any settings file's ``enabledPlugins`` or in
    ``installed_plugins.json``. Keyed by ``<id>@<marketplace>``, sorted by key."""
    locations = _settings_locations(workspace_root)
    registry = _read_registry()

    enabled_at: dict[str, set[str]] = {}
    disabled_at: dict[str, set[str]] = {}
    for label, settings_file in locations:
        for key, value in _read_enabled_plugins(settings_file).items():
            bucket = enabled_at if value else disabled_at
            bucket.setdefault(key, set()).add(label)

    installed_scopes: dict[str, set[str]] = {}
    for key, entries in registry.items():
        for entry in entries:
            scope = entry.get("scope", "?")
            path = entry.get("projectPath")
            installed_scopes.setdefault(key, set()).add(
                f"{scope}:{path}" if path else scope
            )

    all_ids = sorted(set(enabled_at) | set(disabled_at) | set(installed_scopes))
    result: dict[str, PluginState] = {}
    for plugin_id in all_ids:
        marketplace = plugin_id.split("@", 1)[1] if "@" in plugin_id else ""
        install_path = _install_path_for(registry.get(plugin_id, []))
        ships_sl = bool(
            install_path and (install_path / "scripts" / "statusline.py").is_file()
        )
        result[plugin_id] = PluginState(
            plugin_id=plugin_id,
            marketplace=marketplace,
            enabled_at=tuple(sorted(enabled_at.get(plugin_id, ()))),
            disabled_at=tuple(sorted(disabled_at.get(plugin_id, ()))),
            installed_scopes=tuple(sorted(installed_scopes.get(plugin_id, ()))),
            ships_status_line=ships_sl,
        )
    return result


def _print_plugin_block(state: PluginState) -> None:
    """One plugin's aggregated state — shared by the bare report and the `--apply` loop."""
    print(f"\n=== {state.plugin_id} ===")
    print(
        "  enabled at:      "
        + (", ".join(state.enabled_at) if state.enabled_at else "(nowhere — ghost)")
    )
    if state.disabled_at:
        print("  disabled at:     " + ", ".join(state.disabled_at))
    print(
        "  files installed: "
        + (
            ", ".join(state.installed_scopes)
            if state.installed_scopes
            else "(not in the registry)"
        )
    )
    if state.ships_status_line:
        print("  ships a status line (moving it breaks the `statusLine` wiring)")


def print_audit_report(audit: dict[str, PluginState]) -> None:
    """Print the bare `pinky plugins reconcile` audit — one block per plugin, facts only.

    Takes the already-computed audit, so "n'écrit rien" holds by construction: this function
    only reaches `print`. Facts only, every plugin, no filtering and no recommendation
    (NFR-0023-16, ASS-0023-19, FR-0023-33) — where it is enabled / disabled / has files, and
    whether it ships a status line. The `--apply` loop is what proposes a target; the per-plugin
    placement recommendation lives in the chantier story for the human, never coded here.
    """
    if not audit:
        print("No plugin found in any settings file or the install registry.")
        return
    for state in audit.values():
        _print_plugin_block(state)


# ── `--apply`: place each plugin, purge every enable that does not match ────────

_DECISION_PREFIX = "reconcile:"
_ANSWER_ALIASES = {"user": "u", "project": "p", "uninstall": "x", "skip": "s"}


def _spec_parts(spec: str) -> tuple[str, str | None]:
    plugin_id, _, marketplace = spec.partition("@")
    return plugin_id, (marketplace or None)


def _label_to_settings(workspace_root: Path) -> dict[str, Path]:
    """`enabled_at` / `disabled_at` label → the settings file that carries that key."""
    return dict(_settings_locations(workspace_root))


def _pop_key(settings_file: Path, spec: str) -> bool:
    """Delete `spec` from one settings file's `enabledPlugins`, recording the removal in the
    installer ledger (IMP-0023-22). Returns True when a key was actually removed."""
    if not settings_file.is_file():
        return False
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if spec not in data.get("enabledPlugins", {}):
        return False
    del data["enabledPlugins"][spec]
    settings_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    state_file.record_posed(
        f"enabledPlugins:{spec}@{settings_file}",
        path=str(settings_file),
        value="reconcile-removed",
    )
    return True


def _uninstall_at_scope(spec: str, scope: str, cwd: Path | None) -> None:
    """`claude plugin uninstall <spec> --scope <scope>` — the CLI clears both the `enabledPlugins`
    key and the `installed_plugins.json` entry at that scope, which `_pop_key` alone cannot."""
    subprocess.run(
        ["claude", "plugin", "uninstall", spec, "--scope", scope, "--yes"],
        check=True,
        cwd=str(cwd) if cwd else None,
    )


def _project_scopes_by_dir(state: PluginState) -> dict[Path, str]:
    """`{resolved projectPath: scope}` for every non-user registry entry — a project/local
    directory that has real installed files, not just a bare `@inline` settings key."""
    by_dir: dict[Path, str] = {}
    for scoped in state.installed_scopes:
        scope, _, path = scoped.partition(":")
        if path:
            by_dir[Path(path).resolve()] = scope
    return by_dir


def _purge_other_enables(
    spec: str,
    state: PluginState,
    label_map: dict[str, Path],
    *,
    keep: set[str],
) -> None:
    """Remove every enable for `spec` whose directory is not in `keep`. `keep` holds
    `str(Path.home())` for a user target, the chosen project dirs otherwise.

    A directory that also has a registry entry (a real project/local install, e.g. one pulled in
    as a dependency) is removed with `claude plugin uninstall --scope <scope>` so the
    `installed_plugins.json` entry goes too — `setup/rules.py::resolve_targets_for_plugin` reads
    that registry, so a lingering entry keeps shipping the plugin's rules to a ghost dir. A bare
    `@inline` key (no registry entry) is popped straight out of its settings file.
    """
    keep_resolved = {Path(k).resolve() for k in keep}
    scope_by_dir = _project_scopes_by_dir(state)
    for label in {*state.enabled_at, *state.disabled_at}:
        settings = label_map.get(label)
        if settings is None:
            continue
        target_dir = settings.parent.parent.resolve()
        if target_dir in keep_resolved:
            continue
        if label == "user" and state.is_user_enabled:
            plugin_install.drop_user_scope(*_spec_parts(spec))
        elif target_dir in scope_by_dir:
            _uninstall_at_scope(spec, scope_by_dir[target_dir], target_dir)
            state_file.record_posed(
                f"enabledPlugins:{spec}@{settings}",
                path=str(settings),
                value="reconcile-removed",
            )
        else:
            _pop_key(settings, spec)


def _uninstall_everywhere(
    spec: str, state: PluginState, label_map: dict[str, Path]
) -> None:
    """`claude plugin uninstall` once per registry scope the plugin occupies (FR-0023-37), then
    sweep any settings key the CLI did not clear — a pure `@inline` key has no registry entry, so
    the first loop is empty and it is popped straight out of its file."""
    for scoped in state.installed_scopes:
        scope, _, path = scoped.partition(":")
        _uninstall_at_scope(spec, scope, Path(path) if path else None)
    for label in {*state.enabled_at, *state.disabled_at}:
        if label in label_map:
            _pop_key(label_map[label], spec)


def _decision_still_holds(
    recorded: str, state: PluginState, label_map: dict[str, Path]
) -> bool:
    """Does the machine still sit where a prior `--apply` left this plugin? If so a re-run skips
    it (NFR-0023-14). `skip` records nothing, so it is never seen here — always re-prompted."""
    if recorded == "uninstall":
        return not (state.enabled_at or state.disabled_at or state.installed_scopes)
    if recorded == "user":
        return state.enabled_at == ("user",) and not state.disabled_at
    if recorded.startswith("project:"):
        want = set(recorded.removeprefix("project:").split(","))
        have = {
            str(label_map[label].parent.parent)
            for label in state.enabled_at
            if label in label_map
        }
        return "user" not in state.enabled_at and not state.disabled_at and have == want
    return False


def _ensure_user_enabled(spec: str, state: PluginState) -> None:
    if not state.is_user_enabled:
        plugin_install.install_plugin_files(*_spec_parts(spec))


def apply_reconcile(workspace_root: Path) -> None:
    """Interactive `pinky plugins reconcile --apply`: walk every audited plugin, show its state,
    ask where it belongs (`user` / `project` wizard / `uninstall` / `skip`), then make the machine
    match — including removing every enable that does not fit the chosen target (FR-0023-34/35).

    Refuses a non-interactive shell rather than guessing (FR-0023-39). Each decision is recorded
    in the installer ledger so a re-run only revisits what is still divergent (NFR-0023-14).
    """
    if not sys.stdin.isatty():
        print(
            "`plugins reconcile --apply` needs a terminal to ask — refusing to guess.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    label_map = _label_to_settings(workspace_root)
    for spec, state in audit_plugins(workspace_root).items():
        recorded = state_file.posed_value(_DECISION_PREFIX + spec)
        if recorded is not None and _decision_still_holds(recorded, state, label_map):
            continue

        _print_plugin_block(state)
        plugin_id, marketplace = _spec_parts(spec)
        default = "u" if state.ships_status_line else "s"
        if state.ships_status_line:
            print(
                "  ⚠  moving a status-line plugin breaks the `statusLine` wiring — "
                "keep it at user unless `pinky install --plugin` will re-wire it."
            )
        raw = (
            input(
                f"  target — (u)ser / (p)roject / (x) uninstall / (s)kip [{default}]: "
            )
            .strip()
            .lower()
        )
        answer = _ANSWER_ALIASES.get(raw, raw) or default

        if answer == "s":
            continue
        if answer == "u":
            _ensure_user_enabled(spec, state)
            _purge_other_enables(spec, state, label_map, keep={str(Path.home())})
            decision = "user"
        elif answer == "p":
            roots = run_marketplace_wizard(workspace_root, plugin_id, marketplace)
            if roots == [Path.home()]:  # user picked "u" inside the wizard after all
                _ensure_user_enabled(spec, state)
                _purge_other_enables(spec, state, label_map, keep={str(Path.home())})
                decision = "user"
            else:
                _purge_other_enables(
                    spec, state, label_map, keep={str(r) for r in roots}
                )
                decision = "project:" + ",".join(sorted(str(r) for r in roots))
        elif answer == "x":
            if input(f"  uninstall {spec} everywhere? [y/N]: ").strip().lower() not in (
                "y",
                "yes",
            ):
                print("  left unchanged.")
                continue
            _uninstall_everywhere(spec, state, label_map)
            decision = "uninstall"
        else:
            print(f"  unrecognised answer {answer!r} — skipped.", file=sys.stderr)
            continue

        state_file.record_posed(
            _DECISION_PREFIX + spec,
            path=str(state_file.STATE_FILE_PATH),
            value=decision,
        )
