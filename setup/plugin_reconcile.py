"""setup/plugin_reconcile.py — audit where every known plugin is actually enabled.

`pinky claude-plugin list` needs the real picture before it can ask the user to fix it. Two
registries, deliberately not merged:

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
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import plugin_install, state_file, style
from .plugin_scope import list_targets_at_depth, run_marketplace_wizard

_USER_CLAUDE = Path.home() / ".claude"
_REGISTRY = _USER_CLAUDE / "plugins" / "installed_plugins.json"


@dataclass(frozen=True, eq=False)
class _ScopeLabels:
    """Sorted, duplicate-free scope labels — 'user', a directory label, or its '(local)' variant.

    Proxies `tuple[str, ...]` (iteration, length, equality against a plain tuple) so the existing
    `in`/`join`/`==`/set-unpacking call sites need no change.
    """

    values: tuple[str, ...] = ()

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _ScopeLabels):
            return self.values == other.values
        if isinstance(other, tuple):
            return self.values == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.values)


@dataclass(frozen=True)
class PluginState:
    """Everything the reconcile flow needs to know about one plugin, by its ``<id>@<marketplace>``
    key. ``enabled_at`` / ``disabled_at`` / ``installed_scopes`` are sorted, duplicate-free."""

    plugin_id: str
    marketplace: str
    enabled_at: _ScopeLabels
    disabled_at: _ScopeLabels
    installed_scopes: _ScopeLabels
    ships_status_line: bool
    required_by: _ScopeLabels = _ScopeLabels()

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


def _read_manifest(install_path: Path) -> dict:
    """A plugin's own `.claude-plugin/plugin.json` (the manifest location Claude Code's plugin
    system requires) — `{}` if absent or malformed, same tolerance as the rest of this module."""
    manifest = install_path / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _dependents_by_id(registry: dict[str, list[dict]]) -> dict[str, set[str]]:
    """Bare plugin id -> the bare ids of every installed plugin whose manifest declares it in
    `dependencies`. Claude Code resolves and installs these itself (a plugin manifest's
    `dependencies` field) — a scope that looks orphaned for the dependency (`pc-privacy@user`
    with no direct reason of its own) can be recognised as required by the dependent
    (`pc-craft@user`) instead of judged as drift by `audit_plugins`'s caller.

    A `dependencies` entry may be a bare id (`pc-core`) or `id@marketplace`
    (`pc-privacy@pinky-agentic-plugins`) — both are keyed here by the bare id, since that is what
    `audit_plugins` looks up (`required_by=dependents.get(bare_id, ())`).
    """
    dependents: dict[str, set[str]] = {}
    for key, entries in registry.items():
        install_path = _install_path_for(entries)
        if install_path is None:
            continue
        deps = _read_manifest(install_path).get("dependencies", [])
        if not isinstance(deps, list):
            continue
        bare_id = key.split("@", 1)[0]
        for dep in deps:
            if isinstance(dep, str):
                dependents.setdefault(dep.split("@", 1)[0], set()).add(bare_id)
    return dependents


def audit_plugins(workspace_root: Path) -> dict[str, PluginState]:
    """One `PluginState` per plugin id found in any settings file's ``enabledPlugins`` or in
    ``installed_plugins.json``. Keyed by ``<id>@<marketplace>``, sorted by key."""
    locations = _settings_locations(workspace_root)
    registry = _read_registry()
    dependents = _dependents_by_id(registry)

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
        bare_id = plugin_id.split("@", 1)[0]
        install_path = _install_path_for(registry.get(plugin_id, []))
        ships_sl = bool(
            install_path and (install_path / "scripts" / "statusline.py").is_file()
        )
        result[plugin_id] = PluginState(
            plugin_id=plugin_id,
            marketplace=marketplace,
            enabled_at=_ScopeLabels(tuple(sorted(enabled_at.get(plugin_id, ())))),
            disabled_at=_ScopeLabels(tuple(sorted(disabled_at.get(plugin_id, ())))),
            installed_scopes=_ScopeLabels(
                tuple(sorted(installed_scopes.get(plugin_id, ())))
            ),
            ships_status_line=ships_sl,
            required_by=_ScopeLabels(tuple(sorted(dependents.get(bare_id, ())))),
        )
    return result


def enabled_plugin_names(workspace_root: Path) -> frozenset[str]:
    """Bare ids of every plugin actually enabled somewhere — narrower than every key
    `audit_plugins` carries: a plugin that is only explicitly disabled, or that carries just a
    stale registry entry with nothing ever turned on (`PluginState.is_ghost`), is not "installed"
    for the curated picker's pre-check."""
    return frozenset(
        state.plugin_id.split("@", 1)[0]
        for state in audit_plugins(workspace_root).values()
        if not state.is_ghost
    )


def _is_always_on(plugin_id: str) -> bool:
    """Is the plugin (bare id or ``id@marketplace``) in ``plugin_install.KEEP_USER_SCOPE``?"""
    return plugin_id.split("@", 1)[0] in plugin_install.KEEP_USER_SCOPE


def keeps_user_scope(state: PluginState) -> bool:
    """A plugin that belongs at user scope whatever the wizard would pick: it ships a status line
    (a move breaks the `statusLine` wiring) or it is always-on (`plugin_install.KEEP_USER_SCOPE`)."""
    return state.ships_status_line or _is_always_on(state.plugin_id)


def _print_plugin_block(state: PluginState, *, color: bool = False) -> None:
    """One plugin's aggregated state — shared by the bare report and the `--apply` loop."""
    print(f"\n=== {style.paint(state.plugin_id, style.BOLD, color=color)} ===")
    enabled = (
        ", ".join(state.enabled_at)
        if state.enabled_at
        else style.paint("(nowhere — ghost)", style.RED_BOLD, color=color)
    )
    print(f"  enabled at:      {enabled}")
    if state.disabled_at:
        print("  disabled at:     " + ", ".join(state.disabled_at))
    print(
        "  files installed: "
        + (
            ", ".join(state.installed_scopes)
            if state.installed_scopes
            else style.paint("(not in the registry)", style.DIM, color=color)
        )
    )
    if state.ships_status_line:
        print("  ships a status line (moving it breaks the `statusLine` wiring)")
    elif _is_always_on(state.plugin_id):
        print("  always-on — belongs at user scope")
    if state.required_by:
        print("  required by:     " + ", ".join(state.required_by))


def print_audit_report(audit: dict[str, PluginState], *, color: bool = False) -> None:
    """Print the bare `pinky claude-plugin list` audit — one block per plugin, facts only.

    Takes the already-computed audit, so "n'écrit rien" holds by construction: this function
    only reaches `print`. Facts only, every plugin, no filtering and no recommendation — where
    it is enabled / disabled / has files, and whether it ships a status line. The `--apply` loop
    is what proposes a target; the per-plugin placement recommendation is a human decision,
    never coded here. `color` paints headers and the ghost flag the way `setup/doctor.py`
    does — off by default, byte-identical output.
    """
    if not audit:
        print("No plugin found in any settings file or the install registry.")
        return
    for state in audit.values():
        _print_plugin_block(state, color=color)


# ── `--apply`: place each plugin, purge every enable that does not match ────────

_DECISION_PREFIX = "reconcile:"
_ANSWER_ALIASES = {"user": "u", "project": "p", "uninstall": "x", "skip": "s"}


def _spec_parts(spec: str) -> tuple[str, str | None]:
    plugin_id, _, marketplace = spec.partition("@")
    return plugin_id, (marketplace or None)


def resolve_spec(
    plugin_id: str, marketplace: str | None, audit: dict[str, PluginState]
) -> str:
    """The audit key (`<id>@<marketplace>`) a `--plugin` name refers to.

    A given marketplace is taken as is. Without one, the audit's keys carrying the bare id decide:
    one match is the answer, none leaves the bare id (a first install, nothing recorded yet), and
    several ask the user which marketplace — never a guess.
    """
    if marketplace:
        return f"{plugin_id}@{marketplace}"
    candidates = sorted(key for key in audit if _spec_parts(key)[0] == plugin_id)
    if len(candidates) <= 1:
        return candidates[0] if candidates else plugin_id
    for i, key in enumerate(candidates):
        print(f"  {i}) {_spec_parts(key)[1]}")
    answer = input(f"Which marketplace carries {plugin_id}? ").strip()
    try:
        return candidates[int(answer)]
    except (ValueError, IndexError):
        print(f"Invalid choice: {answer!r}", file=sys.stderr)
        raise SystemExit(1) from None


def label_to_settings(workspace_root: Path) -> dict[str, Path]:
    """`enabled_at` / `disabled_at` label → the settings file that carries that key. Public: also
    called from `cli.py`'s `--plugin` flow (rescope-on-reinstall), not just `apply_reconcile`."""
    return dict(_settings_locations(workspace_root))


def _rescope_labels(state: PluginState, *, include_disabled: bool) -> set[str]:
    """The labels a rescope may act on. `include_disabled=False` leaves `disabled_at` alone: a
    `false` key is a deliberate "parent wins, off here" opt-out, not scope accumulation, so the
    `pinky claude-plugin install` path must not silently strip it (it only ever *adds* a scope).
    `apply_reconcile` passes `True` — consolidating a plugin to one scope is meant to clear stale
    disables too."""
    return {*state.enabled_at, *(state.disabled_at if include_disabled else ())}


def stale_labels(
    state: PluginState,
    label_map: dict[str, Path],
    *,
    keep: Iterable[str],
    include_disabled: bool = True,
) -> list[str]:
    """Which of `state`'s enabled (and, unless `include_disabled=False`, disabled) labels fall
    outside `keep` — the preview `purge_other_enables` doesn't expose on its own, so a caller can
    show/confirm before acting instead of purging blind. Same directory-matching as
    `purge_other_enables`, read-only."""
    keep_resolved = {Path(k).resolve() for k in keep}
    stale = []
    for label in _rescope_labels(state, include_disabled=include_disabled):
        settings = label_map.get(label)
        if settings is None:
            continue
        if settings.parent.parent.resolve() not in keep_resolved:
            stale.append(label)
    return sorted(stale)


def _pop_key(settings_file: Path, spec: str) -> bool:
    """Delete `spec` from one settings file's `enabledPlugins`, recording the removal in the
    installer ledger. Returns True when a key was actually removed."""
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


def pop_enable_key(settings_file: Path, spec: str) -> bool:
    """Public wrapper for `_pop_key` — `setup/plugin_enable.py` removes a bare `@inline` enable
    (no registry entry, so no `claude plugin uninstall` scope applies) the same way this module's
    own purge path does, rather than re-implementing the settings-file edit."""
    return _pop_key(settings_file, spec)


def _uninstall_at_scope(spec: str, scope: str, cwd: Path | None) -> None:
    """`claude plugin uninstall <spec> --scope <scope>` — the CLI clears both the `enabledPlugins`
    key and the `installed_plugins.json` entry at that scope, which `_pop_key` alone cannot."""
    subprocess.run(
        ["claude", "plugin", "uninstall", spec, "--scope", scope, "--yes"],
        check=True,
        cwd=str(cwd) if cwd else None,
    )


def uninstall_at_scope(spec: str, scope: str, cwd: Path | None) -> None:
    """Public wrapper for `_uninstall_at_scope` — `setup/plugin_enable.py` removes a
    registry-backed project enable the same way this module's own purge path does, rather than
    re-issuing the `claude plugin uninstall` call by hand."""
    _uninstall_at_scope(spec, scope, cwd)


def _project_scopes_by_dir(state: PluginState) -> dict[Path, str]:
    """`{resolved projectPath: scope}` for every non-user registry entry — a project/local
    directory that has real installed files, not just a bare `@inline` settings key."""
    by_dir: dict[Path, str] = {}
    for scoped in state.installed_scopes:
        scope, _, path = scoped.partition(":")
        if path:
            by_dir[Path(path).resolve()] = scope
    return by_dir


def purge_other_enables(
    spec: str,
    state: PluginState,
    label_map: dict[str, Path],
    *,
    keep: Iterable[str],
    include_disabled: bool = True,
) -> None:
    """Remove every enable for `spec` whose directory is not in `keep`. `keep` holds
    `str(Path.home())` for a user target, the chosen project dirs otherwise. Public: also called
    from `cli.py`'s `--plugin` flow, not just `apply_reconcile`.

    `include_disabled=False` (the `--plugin` path) leaves `disabled_at` keys untouched — a
    deliberate opt-out is not scope accumulation. See `_rescope_labels`.

    A directory that also has a registry entry (a real project/local install, e.g. one pulled in
    as a dependency) is removed with `claude plugin uninstall --scope <scope>` so the
    `installed_plugins.json` entry goes too — `setup/rules.py::resolve_targets_for_plugin` reads
    that registry, so a lingering entry keeps shipping the plugin's rules to a ghost dir. A bare
    `@inline` key (no registry entry) is popped straight out of its settings file.
    """
    keep_resolved = {Path(k).resolve() for k in keep}
    scope_by_dir = _project_scopes_by_dir(state)
    for label in _rescope_labels(state, include_disabled=include_disabled):
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
    """`claude plugin uninstall` once per registry scope the plugin occupies, then
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
    it. `skip` records nothing, so it is never seen here — always re-prompted."""
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
    """Interactive `pinky claude-plugin reconcile`: walk every audited plugin, show its state,
    ask where it belongs (`user` / `project` wizard / `uninstall` / `skip`), then make the machine
    match — including removing every enable that does not fit the chosen target.

    Refuses a non-interactive shell rather than guessing. Each decision is recorded
    in the installer ledger so a re-run only revisits what is still divergent.
    """
    if not sys.stdin.isatty():
        print(
            "`plugins reconcile --apply` needs a terminal to ask — refusing to guess.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    label_map = label_to_settings(workspace_root)
    color = style.use_color()
    for spec, state in audit_plugins(workspace_root).items():
        recorded = state_file.posed_value(_DECISION_PREFIX + spec)
        if recorded is not None and _decision_still_holds(recorded, state, label_map):
            continue

        _print_plugin_block(state, color=color)
        plugin_id, marketplace = _spec_parts(spec)
        default = "u" if keeps_user_scope(state) else "s"
        if state.ships_status_line:
            print(
                "  ⚠️  moving a status-line plugin breaks the `statusLine` wiring — "
                "keep it at user unless `pinky claude-plugin install` will re-wire it."
            )
        elif _is_always_on(plugin_id):
            print(
                "  ⚠️  always-on plugin — keep it at user scope unless you know it moved."
            )
        if state.required_by:
            print(
                f"  ⚠️  {', '.join(state.required_by)} declare(s) this as a dependency — "
                "removing a scope here may break them too."
            )
        raw = (
            input(
                style.paint(
                    f"  target — (u)ser / (p)roject / (x) uninstall / (s)kip [{default}]: ",
                    style.BOLD,
                    color=color,
                )
            )
            .strip()
            .lower()
        )
        answer = _ANSWER_ALIASES.get(raw, raw) or default

        if answer == "s":
            continue
        if answer == "u":
            _ensure_user_enabled(spec, state)
            purge_other_enables(spec, state, label_map, keep={str(Path.home())})
            decision = "user"
        elif answer == "p":
            # this loop's own prompt already asked user/project — the wizard skips its Q1
            try:
                install_path = plugin_install.resolve_install_path(
                    plugin_id, marketplace
                )
            except FileNotFoundError:
                # audited from a registry/settings entry whose files are gone — the wizard still
                # re-enables the plugin, it just can't check for a language server to wire.
                install_path = None
            roots = run_marketplace_wizard(
                workspace_root,
                plugin_id,
                marketplace,
                skip_scope_question=True,
                install_path=install_path,
            )
            purge_other_enables(spec, state, label_map, keep={str(r) for r in roots})
            decision = "project:" + ",".join(sorted(str(r) for r in roots))
        elif answer == "x":
            if input(
                style.paint(
                    f"  uninstall {spec} everywhere? [y/N]: ",
                    style.BOLD,
                    color=color,
                )
            ).strip().lower() not in (
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
