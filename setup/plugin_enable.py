"""setup/plugin_enable.py — `pinky claude-plugin enable`/`disable`: the plugin x target table,
`--scope`, the plan-then-`[y/N]` convention, and the rules that follow a plugin to its scope.

Reuses `plugin_reconcile.audit_plugins`/`label_to_settings` for the state read (one source of
truth, IMP-0024-31) and `plugin_install`'s scope primitives for the write — this module only adds
the table/diff/plan layer on top, plus the rules side effect (`setup/rules.py`).

A settings label ending in " (local)" is `pc-autodiscovery`'s per-session state
(`settings.local.json`) — never listed, never touched, never counted as an enable to add or remove
(IMP-0024-30). The same discipline applies to a registry entry whose `scope` is `local`: it is
`plugin_install`'s own bookkeeping (a language server, an autodiscovery-managed install), not
something `enable`/`disable` places or removes.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import plugin_install, plugin_reconcile, rules, state_file
from .plugin_reconcile import PluginState, _ScopeLabels

USER_LABEL = "user"


def _is_local_label(label: str) -> bool:
    return label.endswith(" (local)")


def _current_enabled_labels(state: PluginState) -> set[str]:
    """`state.enabled_at`, with every `(local)` label dropped — a session-scope enable is neither
    shown in the table nor a candidate for removal (IMP-0024-30)."""
    return {label for label in state.enabled_at if not _is_local_label(label)}


def _registry_scope_at(state: PluginState, target_dir: Path) -> str | None:
    """The registry `scope` recorded for `target_dir`, or `None` if it never carries a registry
    entry (a bare `@inline` settings key)."""
    for scoped in state.installed_scopes:
        scope, _, path = scoped.partition(":")
        if path and Path(path).resolve() == target_dir:
            return scope
    return None


def target_dir_for_label(
    label: str, label_map: dict[str, Path], workspace_root: Path
) -> Path:
    """The directory a settings label enables the plugin at — `workspace_root` for `user` (the
    same convention `setup/rules.py::resolve_targets_for_plugin` uses for a user-scope install)."""
    if label == USER_LABEL:
        return workspace_root.resolve()
    return label_map[label].parent.parent.resolve()


def _active_dirs_by_bare_id(
    audit: dict[str, PluginState], label_map: dict[str, Path], workspace_root: Path
) -> dict[str, set[Path]]:
    """Every plugin's currently-active directories, one entry per bare id, derived from settings
    labels rather than `installed_plugins.json` — a plugin enabled through a bare `@inline`
    settings key (no registry entry at all) is otherwise invisible to a registry-only read, which
    is exactly what lets an unrelated plugin's `disable` purge its rules as collateral (or leave
    its own rules orphaned when it is the one being disabled) — see
    `rules.rules_report_for_plugin_at_targets`'s `active_dirs_by_plugin`."""
    result: dict[str, set[Path]] = {}
    for spec, state in audit.items():
        bare_id = spec.partition("@")[0]
        dirs = {
            target_dir_for_label(label, label_map, workspace_root)
            for label in _current_enabled_labels(state)
        }
        result.setdefault(bare_id, set()).update(dirs)
    return result


@dataclass(frozen=True)
class ScopeRow:
    """One line of the plugin x target table: a plugin, a settings label, whether it starts
    checked."""

    index: int
    plugin_id: str
    label: str
    checked: bool


def build_rows(
    plugin_states: Sequence[tuple[str, PluginState]], label_map: dict[str, Path]
) -> list[ScopeRow]:
    """One `ScopeRow` per (plugin, label) pair — every non-local label known to `label_map`, in
    its existing order (`user` first, then the workspace root, then each group/repo), prefilled
    from `state.enabled_at` (FR-0024-45)."""
    rows: list[ScopeRow] = []
    index = 0
    for spec, state in plugin_states:
        enabled = _current_enabled_labels(state)
        for label in label_map:
            if _is_local_label(label):
                continue
            rows.append(ScopeRow(index, spec, label, label in enabled))
            index += 1
    return rows


def render_scope_table(rows: Sequence[ScopeRow]) -> str:
    """The table's exact text — one numbered, checkbox-prefixed line per row, so it can be typed
    back as toggle indices."""
    return "\n".join(
        f"{row.index:>3}) [{'x' if row.checked else ' '}] {row.plugin_id} @ {row.label}"
        for row in rows
    )


def _parse_toggle_indices(answer: str, count: int) -> set[int]:
    """Space- or comma-separated row indices to flip — empty input flips nothing (keep the table
    as shown)."""
    tokens = answer.replace(",", " ").split()
    picked: set[int] = set()
    for tok in tokens:
        idx = int(
            tok
        )  # ValueError propagates — an invalid index must stop the flow, not guess
        if not 0 <= idx < count:
            raise ValueError(f"index {idx} out of range 0-{count - 1}")
        picked.add(idx)
    return picked


def _apply_toggles(rows: Sequence[ScopeRow], toggled: set[int]) -> list[ScopeRow]:
    """`rows` with every index in `toggled` flipped — the table after the user's answer."""
    return [
        ScopeRow(row.index, row.plugin_id, row.label, not row.checked)
        if row.index in toggled
        else row
        for row in rows
    ]


def _desired_labels(rows: Sequence[ScopeRow], plugin_id: str) -> set[str]:
    """The checked labels for one plugin, after the table (or its toggle) settled."""
    return {row.label for row in rows if row.plugin_id == plugin_id and row.checked}


@dataclass(frozen=True)
class PluginPickRow:
    """One row of the "which plugin(s)" checkbox list (FR-0024-33) — which plugin, distinct from
    `ScopeRow` (which plugin × which target)."""

    index: int
    name: str
    checked: bool


def build_plugin_pick_rows(
    curated_names: Iterable[str], installed_names: Iterable[str]
) -> list[PluginPickRow]:
    """Every curated name plus every installed name, deduped and sorted, installed ones
    pre-checked (FR-0024-36). No installed plugin at all → every row checked instead (FR-0024-37)
    — a fresh machine bootstraps with the full curated set by default."""
    installed = set(installed_names)
    names = sorted(set(curated_names) | installed)
    fully_checked = not installed
    return [
        PluginPickRow(i, name, checked=fully_checked or name in installed)
        for i, name in enumerate(names)
    ]


def render_plugin_pick_table(rows: Sequence[PluginPickRow]) -> str:
    """Same shape as `render_scope_table` — a numbered, checkbox-prefixed line per row."""
    return "\n".join(
        f"{row.index:>3}) [{'x' if row.checked else ' '}] {row.name}" for row in rows
    )


def pick_plugins(
    curated_names: Iterable[str], installed_names: Iterable[str]
) -> list[str]:
    """`install`/`enable`'s "no name" entry point (FR-0024-33): an interactive checkbox over
    curated ∪ installed plugin names, returning the checked ones. Errors rather than guessing when
    there is nothing to pick from or no tty to ask — same discipline as `run`'s own table."""
    if not sys.stdin.isatty():
        # NFR-0024-35: a non-interactive shell always needs the plugin(s) named explicitly —
        # checked ahead of "anything to pick from" so this message never depends on what happens
        # to be curated/installed on the machine running it.
        print("Non-interactive shell — name the plugin(s) explicitly.", file=sys.stderr)
        raise SystemExit(1)
    rows = build_plugin_pick_rows(curated_names, installed_names)
    if not rows:
        print("No curated or installed plugin to pick from.", file=sys.stderr)
        raise SystemExit(1)
    print(render_plugin_pick_table(rows))
    answer = input(
        "Toggle indices to flip (space-separated), Enter to keep as shown: "
    ).strip()
    if answer:
        try:
            toggled = _parse_toggle_indices(answer, len(rows))
        except ValueError as exc:
            print(f"Invalid choice: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
        rows = [
            PluginPickRow(row.index, row.name, not row.checked)
            if row.index in toggled
            else row
            for row in rows
        ]
    return [row.name for row in rows if row.checked]


def _desired_from_scope_flags(
    current: set[str], scope_labels: set[str], *, action: str
) -> set[str]:
    """`--scope` bypasses the table entirely: `enable` adds the named labels to what is already
    enabled, `disable` removes them — never a full replacement of the other scopes (FR-0024-46)."""
    if action == "enable":
        return current | scope_labels
    if action == "disable":
        return current - scope_labels
    raise ValueError(f"unknown action: {action!r}")


def _redundant_labels(
    desired: set[str], label_map: dict[str, Path], workspace_root: Path
) -> list[str]:
    """Which of `desired`'s directory labels sit strictly under another desired label's directory
    — flagged, never auto-removed (FR-0024-51). `user` is never a directory ancestor of anything
    and is excluded from the comparison."""
    dirs = {
        label: target_dir_for_label(label, label_map, workspace_root)
        for label in desired
        if label != USER_LABEL
    }
    redundant = []
    for label, target in dirs.items():
        if any(
            other_dir != target and target.is_relative_to(other_dir)
            for other_label, other_dir in dirs.items()
            if other_label != label
        ):
            redundant.append(label)
    return sorted(redundant)


@dataclass(frozen=True)
class ScopeDiff:
    """`desired` against `current` — what a plan shows before `[y/N]`."""

    added: list[str]
    removed: list[str]
    unchanged: list[str]
    redundant: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed)


def _compute_diff(
    current: set[str],
    desired: set[str],
    label_map: dict[str, Path],
    workspace_root: Path,
) -> ScopeDiff:
    return ScopeDiff(
        added=sorted(desired - current),
        removed=sorted(current - desired),
        unchanged=sorted(current & desired),
        redundant=_redundant_labels(desired, label_map, workspace_root),
    )


def render_scope_plan(plugin_id: str, diff: ScopeDiff) -> str:
    """The plan's exact text for one plugin — added / removed / unchanged / redundant, or
    "nothing to do" when there is nothing to add, remove, or flag (NFR-0024-30, NFR-0024-32).

    A redundant scope is surfaced even when `has_changes` is false (FR-0024-51: "signalé, jamais
    silencieux") — an already-redundant enable does not become invisible just because this run
    toggles nothing.
    """
    lines = [f"{plugin_id}:"]
    if not diff.has_changes and not diff.redundant:
        lines.append("  nothing to do")
        return "\n".join(lines)
    if diff.added:
        lines.append("  add: " + ", ".join(diff.added))
    if diff.removed:
        lines.append("  remove: " + ", ".join(diff.removed))
        if USER_LABEL in diff.removed:
            lines.append(
                "  note: removing the user scope may also prune now-unneeded "
                "dependencies (`claude plugin prune`)"
            )
    if diff.unchanged:
        lines.append("  unchanged: " + ", ".join(diff.unchanged))
    if diff.redundant:
        lines.append(
            "  redundant (already covered by an ancestor scope): "
            + ", ".join(diff.redundant)
        )
    return "\n".join(lines)


def _enable_label(
    plugin_id: str,
    marketplace: str | None,
    label: str,
    label_map: dict[str, Path],
    workspace_root: Path,
) -> None:
    if label == USER_LABEL:
        plugin_install.install_plugin_files(plugin_id, marketplace)
        return
    target_dir = target_dir_for_label(label, label_map, workspace_root)
    plugin_install.enable_at_project(plugin_id, target_dir, marketplace)


def _disable_label(
    plugin_id: str,
    marketplace: str | None,
    label: str,
    label_map: dict[str, Path],
    workspace_root: Path,
    state: PluginState,
) -> None:
    if label == USER_LABEL:
        plugin_install.drop_user_scope(plugin_id, marketplace)
        return
    settings = label_map[label]
    target_dir = target_dir_for_label(label, label_map, workspace_root)
    spec = f"{plugin_id}@{marketplace}" if marketplace else plugin_id
    if _registry_scope_at(state, target_dir) == "project":
        plugin_reconcile.uninstall_at_scope(spec, "project", target_dir)
        state_file.record_posed(
            f"enabledPlugins:{spec}@{settings}",
            path=str(settings),
            value="disabled",
        )
    else:
        plugin_reconcile.pop_enable_key(settings, spec)


def _apply_scope_diff(
    plugin_id: str,
    marketplace: str | None,
    diff: ScopeDiff,
    label_map: dict[str, Path],
    workspace_root: Path,
    state: PluginState,
) -> None:
    """Enable at every added label, remove every removed one — `state` is the pre-mutation audit,
    read once by the caller so the "project vs bare key" decision below is not re-derived mid-run."""
    for label in diff.added:
        _enable_label(plugin_id, marketplace, label, label_map, workspace_root)
    for label in diff.removed:
        _disable_label(plugin_id, marketplace, label, label_map, workspace_root, state)


def _apply_rules_diff(
    plugin_id: str,
    diff: ScopeDiff,
    label_map: dict[str, Path],
    workspace_root: Path,
    *,
    apply: bool,
    user_rules_dir: Path | None = None,
    active_dirs_by_plugin: dict[str, set[Path]] | None = None,
) -> dict[Path, rules.RulesReport]:
    """The plugin's rules at every target the diff touches — present at what stays/becomes
    enabled, purged at what stops being enabled (FR-0024-52, 60 to 66). Both directions are
    derived from the diff's own settings labels, not a registry read: `current` (unchanged +
    removed) and `desired` (added + unchanged) are the same labels `_compute_diff` used, so a
    bare `@inline` enable (no `installed_plugins.json` entry) is a valid "previously here" or
    "still here" target just like a registry-backed one — see
    `rules.rules_report_for_plugin_at_targets`, so the plan shown before `[y/N]` is exactly what
    `apply=True` writes after it.

    `active_dirs_by_plugin` (from `_active_dirs_by_bare_id`) gives the sibling-ownership check
    the same settings-label ground truth for every OTHER plugin, so a co-resident inline-only
    sibling's rules are never purged as collateral."""
    desired_dirs = [
        target_dir_for_label(label, label_map, workspace_root)
        for label in (diff.added + diff.unchanged)
    ]
    previous_dirs = [
        target_dir_for_label(label, label_map, workspace_root)
        for label in (diff.unchanged + diff.removed)
    ]
    return rules.rules_report_for_plugin_at_targets(
        plugin_id,
        desired_dirs,
        previous_dirs,
        workspace_root,
        apply=apply,
        user_rules_dir=user_rules_dir,
        active_dirs_by_plugin=active_dirs_by_plugin,
    )


def render_rules_plan(reports: dict[Path, rules.RulesReport]) -> str:
    """One line per target with a non-empty rules diff — silent when every target is unchanged,
    same "say nothing extra" discipline as the scope plan."""
    lines = []
    for target, report in sorted(reports.items()):
        if report.has_changes:
            lines.append(
                f"  rules @ {target}: "
                f"+{len(report.added)} ~{len(report.modified)} -{len(report.purged)}"
            )
    return "\n".join(lines)


def confirm(*, yes: bool, prompt: str = "Apply this plan? [y/N] ") -> bool:
    """The shared plan-then-`[y/N]` gate: `--yes` skips it, a non-interactive shell without `--yes`
    refuses rather than guessing (NFR-0024-30, NFR-0024-31, NFR-0024-35)."""
    if yes:
        return True
    if not sys.stdin.isatty():
        print("Non-interactive shell — pass --yes to apply.", file=sys.stderr)
        raise SystemExit(1)
    return input(prompt).strip().lower() == "y"


def _resolve_scope_flags(
    scope_args: Sequence[str], workspace_root: Path, label_map: dict[str, Path]
) -> set[str]:
    """Every `--scope` value (a workspace-relative path, or `user`) to the settings label it
    names — the same labels the table uses, so `_desired_from_scope_flags` needs no separate code
    path for "which directory did the user mean"."""
    labels: set[str] = set()
    for raw in scope_args:
        if raw == USER_LABEL:
            labels.add(USER_LABEL)
            continue
        target = Path(raw)
        target = (
            target.resolve()
            if target.is_absolute()
            else (workspace_root / raw).resolve()
        )
        match = next(
            (
                label
                for label, settings in label_map.items()
                if not _is_local_label(label)
                and label != USER_LABEL
                and settings.parent.parent.resolve() == target
            ),
            None,
        )
        if match is None:
            print(
                f"--scope {raw!r} is not a known target under {workspace_root}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        labels.add(match)
    return labels


def _split_spec(spec: str, marketplace: str | None) -> tuple[str, str | None]:
    plugin_id, _, spec_marketplace = spec.partition("@")
    return plugin_id, (spec_marketplace or marketplace)


def _empty_state(spec: str, marketplace: str | None) -> PluginState:
    """A first-ever enable: nothing recorded for `spec` yet — every set starts empty."""
    return PluginState(
        plugin_id=spec,
        marketplace=marketplace or "",
        enabled_at=_ScopeLabels(),
        disabled_at=_ScopeLabels(),
        installed_scopes=_ScopeLabels(),
        ships_status_line=False,
    )


@dataclass(frozen=True)
class RunResult:
    """`run`'s outcome — `applied` is non-empty only for `outcome == "applied"`.

    `wire` is `True` for `"applied"` and `"nothing"` — either way the plugin is confirmed on disk,
    exactly where it should be, so a caller like `install` can safely re-resolve its install path
    (a status line, an LSP server) even on a no-op re-run (e.g. after `claude plugin update`).
    `False` for `"declined"` and `"dry_run"`: nothing was confirmed, so nothing was necessarily
    ever fetched — `resolve_install_path` may raise on a plugin no run has ever placed anywhere.
    """

    outcome: str
    applied: list[str]

    @property
    def wire(self) -> bool:
        return self.outcome in ("applied", "nothing")


def run(
    action: str,
    plugin_names: Sequence[str],
    workspace_root: Path,
    *,
    marketplace: str | None = None,
    scope: Sequence[str] | None = None,
    yes: bool = False,
    dry_run: bool = False,
    user_rules_dir: Path | None = None,
) -> RunResult:
    """`pinky claude-plugin enable`/`disable`: one plan across every named plugin, one `[y/N]`.

    `scope` bypasses the interactive table (FR-0024-46): `_desired_from_scope_flags` decides the
    target set directly, no question asked beyond the shared `[y/N]` (skipped too under `--yes`).
    Without it, the table is printed and one toggle-index question adjusts it (FR-0024-44).
    """
    if action not in ("enable", "disable"):
        raise ValueError(f"unknown action: {action!r}")
    if not plugin_names:
        print(
            f"claude-plugin {action} needs at least one plugin name.", file=sys.stderr
        )
        raise SystemExit(1)

    audit = plugin_reconcile.audit_plugins(workspace_root)
    label_map = plugin_reconcile.label_to_settings(workspace_root)
    specs = [
        plugin_reconcile.resolve_spec(name, marketplace, audit) for name in plugin_names
    ]
    states = [audit.get(spec) or _empty_state(spec, marketplace) for spec in specs]
    # Every OTHER plugin's active dirs, by bare id — a named plugin's own entry is overwritten
    # with its post-action dirs as its diff is computed, below.
    active_dirs_by_plugin = _active_dirs_by_bare_id(audit, label_map, workspace_root)

    if scope:
        scope_labels = _resolve_scope_flags(scope, workspace_root, label_map)
        desired_by_spec = {
            spec: _desired_from_scope_flags(
                _current_enabled_labels(state), scope_labels, action=action
            )
            for spec, state in zip(specs, states, strict=True)
        }
    else:
        rows = build_rows(list(zip(specs, states, strict=True)), label_map)
        if rows and sys.stdin.isatty():
            print(render_scope_table(rows))
            answer = input(
                "Toggle indices to flip (space-separated), Enter to keep as shown: "
            ).strip()
            if answer:
                try:
                    toggled = _parse_toggle_indices(answer, len(rows))
                except ValueError as exc:
                    print(f"Invalid choice: {exc}", file=sys.stderr)
                    raise SystemExit(1) from None
                rows = _apply_toggles(rows, toggled)
        else:
            # No tty to ask the table, and no --scope to skip it: `--yes` only ever skips the
            # `[y/N]` confirmation, never substitutes for "which targets" — accepting it here
            # would silently no-op ("nothing to do", exit 0) on a command that looked complete.
            print(
                "Non-interactive shell — pass --scope (no table can be shown).",
                file=sys.stderr,
            )
            raise SystemExit(1)
        desired_by_spec = {spec: _desired_labels(rows, spec) for spec in specs}

    plans = []
    any_changes = False
    for spec, state in zip(specs, states, strict=True):
        plugin_id, plugin_marketplace = _split_spec(spec, marketplace)
        current = _current_enabled_labels(state)
        diff = _compute_diff(current, desired_by_spec[spec], label_map, workspace_root)
        # Fold this spec's own post-action dirs in before the next spec of a multi-plugin batch is
        # planned, so a later plugin sees an earlier one as already active at a shared target.
        active_dirs_by_plugin[plugin_id] = {
            target_dir_for_label(label, label_map, workspace_root)
            for label in (diff.added + diff.unchanged)
        }
        rules_preview = _apply_rules_diff(
            plugin_id,
            diff,
            label_map,
            workspace_root,
            apply=False,
            user_rules_dir=user_rules_dir,
            active_dirs_by_plugin=active_dirs_by_plugin,
        )
        print(render_scope_plan(spec, diff))
        rules_text = render_rules_plan(rules_preview)
        if rules_text:
            print(rules_text)
        if diff.has_changes or any(r.has_changes for r in rules_preview.values()):
            any_changes = True
        plans.append((spec, plugin_id, plugin_marketplace, state, diff))

    if not any_changes:
        print("nothing to do")
        return RunResult("nothing", [])
    if dry_run:
        return RunResult("dry_run", [])
    if not confirm(yes=yes):
        print("cancelled.")
        return RunResult("declined", [])

    for spec, plugin_id, plugin_marketplace, state, diff in plans:
        _apply_scope_diff(
            plugin_id, plugin_marketplace, diff, label_map, workspace_root, state
        )
        _apply_rules_diff(
            plugin_id,
            diff,
            label_map,
            workspace_root,
            apply=True,
            user_rules_dir=user_rules_dir,
            active_dirs_by_plugin=active_dirs_by_plugin,
        )
    print("applied.")
    return RunResult(
        "applied", [spec for spec, _, _, _, diff in plans if diff.has_changes]
    )
