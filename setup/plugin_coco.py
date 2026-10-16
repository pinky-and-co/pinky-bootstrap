"""setup/plugin_coco.py — `pinky claude-plugin coco`: launch Snowflake Cortex Code (`cortex`)
with the same plugins Claude Code has active for the current directory.

One environment in both tools; what does not work under cortex is tolerated, never repaired
here. cortex has no project-scope plugin discovery (nothing under `.cortex/` or the project
`.claude/` loads a plugin), so the only working entry point is one `--plugin-dir <path>` per
plugin on the command line — a global `~/.snowflake/cortex/settings.json` `plugins` array exists
but is refused: it would break the scope model. The plugin set itself is read from the same
scope chain Claude Code resolves: `enabledPlugins` applies per git-repo-root, an ancestor scope
(a group, the workspace root) reaches the repos nested under it, the nearest scope carrying the
key wins, user scope comes last.

Writes nothing — no settings file, no marker inside the plugins. cortex must be launched by
this command: started on its own, it loads no plugin at all.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from . import plugin_enable, plugin_install, plugin_reconcile, style, tui
from .plugin_reconcile import PluginState, _read_manifest

VALIDATE_TIMEOUT = 15.0
_VALIDATE_WORKERS = 8

Picker = plugin_enable.Picker


def project_root(start: Path) -> Path:
    """The directory Claude Code would treat as the project of `start` — the nearest ancestor
    (or `start` itself) holding `.git`. `enabledPlugins` resolves per git-repo-root, so a
    session opened in a repo subdirectory reads the repo root's scope chain, not the
    subdirectory's own.

    Args:
        start: where the session opens (the cwd of the `pinky` invocation).

    Returns:
        The git repo root, or `start` itself when no ancestor carries `.git`.
    """
    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():
            return candidate
    return resolved


def _local_first(labels: Sequence[str]) -> list[str]:
    """Same-directory labels with the `(local)` variant first — `settings.local.json` overrides
    `settings.json` at equal depth, the same precedence Claude Code's own settings follow."""
    local = [label for label in labels if label.endswith(" (local)")]
    plain = [label for label in labels if not label.endswith(" (local)")]
    return [*local, *plain]


def scope_chain_labels(label_map: Mapping[str, Path], target_dir: Path) -> list[str]:
    """Settings labels from the most specific scope to the least: `target_dir`'s own `(local)`
    then plain label, each ancestor's likewise nearest-first, `user` last — the order an
    `enabledPlugins` key is resolved against.

    A directory the audit does not know (above the workspace root, inside a pruned repo
    subtree) carries no label, so it is simply absent from the chain.

    Args:
        label_map: `plugin_reconcile.label_to_settings(workspace_root)`.
        target_dir: the directory whose chain is wanted (a repo root).

    Returns:
        The ordered labels, most specific first, `user` last.
    """
    by_dir: dict[Path, list[str]] = {}
    for label, settings in label_map.items():
        if label == plugin_enable.USER_LABEL:
            continue
        by_dir.setdefault(settings.parent.parent.resolve(), []).append(label)
    resolved = target_dir.resolve()
    chain: list[str] = []
    for directory in (resolved, *resolved.parents):
        labels = by_dir.get(directory)
        if labels:
            chain += _local_first(labels)
    chain.append(plugin_enable.USER_LABEL)
    return chain


def active_specs_for_dir(
    audit: Mapping[str, PluginState],
    label_map: Mapping[str, Path],
    target_dir: Path,
) -> list[str]:
    """Audit keys of every plugin Claude Code loads for a session opened in `target_dir`.

    The first scope of the chain carrying the spec's key decides — `true` active, `false` off
    (a deliberate opt-out of an ancestor's enable). A spec no scope mentions is not active.

    Args:
        audit: `plugin_reconcile.audit_plugins(workspace_root)`.
        label_map: `plugin_reconcile.label_to_settings(workspace_root)`.
        target_dir: the project directory (a repo root — `project_root`).

    Returns:
        The sorted active `<plugin>@<marketplace>` keys.
    """
    chain = scope_chain_labels(label_map, target_dir)
    active: list[str] = []
    for spec in sorted(audit):
        state = audit[spec]
        verdict = next(
            (
                label in state.enabled_at
                for label in chain
                if label in state.enabled_at or label in state.disabled_at
            ),
            None,
        )
        if verdict:
            active.append(spec)
    return active


@dataclass(frozen=True)
class CocoEntry:
    """One plugin of the coco plan: its audit spec, its installed directory (`None` = no
    `installed_plugins.json` entry, the bare `@inline` enable case), and cortex's validation
    verdict — the raw issue lines, `[]` when clean, `None` when unavailable."""

    spec: str
    install_path: Path | None
    description: str
    issues: list[str] | None


def resolve_entry(spec: str) -> CocoEntry:
    """The plugin's on-disk facts for the plan: the directory `claude plugin install` unpacked
    it into (the same copy Claude Code loads) and the description of its `plugin.json`.

    Args:
        spec: the audit key, bare or `<plugin>@<marketplace>`.

    Returns:
        The entry, `install_path=None` when the registry carries no directory for the spec.
    """
    plugin_id, _, marketplace = spec.partition("@")
    try:
        install_path: Path | None = plugin_install.resolve_install_path(
            plugin_id, marketplace or None
        )
    except FileNotFoundError:
        install_path = None
    description = ""
    if install_path is not None:
        raw = _read_manifest(install_path).get("description", "")
        description = raw if isinstance(raw, str) else ""
    return CocoEntry(spec, install_path, description, None)


def parse_validation(output: str) -> list[str] | None:
    """The issue lines of one `cortex plugin validate` run.

    Keeps every ``- [component] file: message`` line raw; the `activation.md` hint and any
    other prose are dropped along the way. An output that opens with cortex's own
    ``Plugin '<name>'`` header but lists no issue reads clean — anything else (empty, a crash
    trace) gives `None`, so the caller reports "validation unavailable" rather than a false
    clean verdict.

    Args:
        output: the command's stdout.

    Returns:
        The raw issue lines, `[]` when clean, `None` when the shape is unexpected.
    """
    issues = [
        line.strip() for line in output.splitlines() if line.strip().startswith("- [")
    ]
    if issues:
        return issues
    return [] if re.search(r"^Plugin '", output, re.MULTILINE) else None


def _validate_one(install_path: Path, timeout: float) -> list[str] | None:
    """`cortex plugin validate` in the plugin's own directory — the form without an argument,
    the only one cortex actually checks."""
    try:
        proc = subprocess.run(
            ["cortex", "plugin", "validate"],
            cwd=install_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_validation(proc.stdout)


def validate_entries(
    entries: Sequence[CocoEntry],
    *,
    timeout: float = VALIDATE_TIMEOUT,
    max_workers: int = _VALIDATE_WORKERS,
) -> dict[str, list[str] | None]:
    """Cortex's validation verdict for every resolvable entry, run in parallel.

    A missing binary, a timeout or an unexpected output gives `None` — unavailable, never
    wrong; an unresolvable entry (no directory to run in) is `None` too. Validation issues do
    not block anything: they are information on the picker's line.

    Args:
        entries: the resolved entries.
        timeout: per-plugin timeout in seconds.
        max_workers: thread-pool size.

    Returns:
        `{spec: issues}` — the raw lines, `[]` when clean, `None` when unavailable.
    """
    to_run = [
        (entry.spec, entry.install_path)
        for entry in entries
        if entry.install_path is not None
    ]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(to_run) or 1)) as pool:
        futures = {
            spec: pool.submit(_validate_one, path, timeout) for spec, path in to_run
        }
    results: dict[str, list[str] | None] = {entry.spec: None for entry in entries}
    results.update({spec: future.result() for spec, future in futures.items()})
    return results


def entry_line(entry: CocoEntry) -> str:
    """One checkbox line: the plugin id, its manifest description, then cortex's validation
    verdict. A warning is shown raw; an unavailable validation says so — never a reassuring
    verdict where the validator did not answer."""
    if entry.install_path is None:
        return f"{entry.spec}  ⚠ unresolved — no installed_plugins.json entry"
    line = (
        entry.spec if not entry.description else f"{entry.spec} — {entry.description}"
    )
    if entry.issues:
        return f"{line}  ⚠ {' · '.join(entry.issues)}"
    if entry.issues is None:
        return f"{line}  ⚠ validation unavailable"
    return line


def pick_entries(
    entries: Sequence[CocoEntry],
    *,
    picker: Picker | None = None,
) -> list[CocoEntry]:
    """The all-prechecked checkbox over every entry — one plugin per line, nothing ever
    unchecked by the command itself.

    Args:
        entries: the resolved, validated entries.
        picker: the checkbox screen — defaults to `tui.run_checklist` at call time, the seam
            a test patches (same discipline as `plugin_enable.pick_plugins`).

    Returns:
        The entries left checked, in their original order.

    Raises:
        KeyboardInterrupt: Ctrl-C on the screen, for the entry point's exit-130 handler.
    """
    picker = picker or tui.run_checklist
    items = [
        tui.ChecklistItem(entry_line(entry), checked=True, key=index)
        for index, entry in enumerate(entries)
    ]
    result = picker(items, title="plugins to load into cortex")
    return [entry for entry, flag in zip(entries, result, strict=True) if flag]


def render_plan(selected: Sequence[CocoEntry], project_dir: Path) -> str:
    """The plan's exact text: one `plugin → directory` line per selected entry, an unresolved
    entry saying so instead.

    Args:
        selected: the entries left checked.
        project_dir: the directory cortex will run in.

    Returns:
        The whole plan, one line per entry under a header naming the project.
    """
    lines = [f"cortex in {project_dir}:"]
    for entry in selected:
        if entry.install_path is None:
            lines.append(
                f"  {entry.spec} — unresolved (no installed_plugins.json entry)"
            )
        else:
            lines.append(f"  {entry.spec} → {entry.install_path}")
    return "\n".join(lines)


def cortex_command(plugin_dirs: Sequence[Path]) -> list[str]:
    """`cortex` with one `--plugin-dir` per resolved plugin directory, in the given order.

    Args:
        plugin_dirs: the installed plugin directories.

    Returns:
        The full argv, `["cortex"]` when no directory resolves.
    """
    args = ["cortex"]
    for directory in plugin_dirs:
        args += ["--plugin-dir", str(directory)]
    return args


def cortex_env(base: Mapping[str, str], project_dir: Path) -> dict[str, str]:
    """The launch environment: `base` plus `CLAUDE_PROJECT_DIR` — cortex never sets it itself,
    and the plugins' hooks and skills read it.

    Args:
        base: the calling process's environment.
        project_dir: the directory cortex runs in.

    Returns:
        The environment to pass to the cortex process.
    """
    return {**base, "CLAUDE_PROJECT_DIR": str(project_dir)}


def run(
    workspace_root: Path,
    *,
    yes: bool = False,
    dry_run: bool = False,
    start_dir: Path | None = None,
    picker: Picker | None = None,
) -> int:
    """`pinky claude-plugin coco`: resolve the directory's active plugins, let the user drop
    any of them on a prechecked checkbox, then launch `cortex` with one `--plugin-dir` per
    resolved plugin. Writes nothing.

    Args:
        workspace_root: the workspace the scope chain resolves against.
        yes: skip the checkbox and the `[y/N]` — every active plugin stays checked (required
            in a non-interactive shell).
        dry_run: print the plan and the command, never launch cortex.
        start_dir: where the command runs (default: the cwd) — its git root is the project.
        picker: the checkbox screen, overridable for tests.

    Returns:
        cortex's exit code; 0 for a dry run, a decline, or nothing to launch.

    Raises:
        SystemExit: `cortex` is not on PATH, or no terminal and no `--yes`.
    """
    if shutil.which("cortex") is None:
        print(
            "`cortex` not found on PATH — install the Snowflake Cortex Code CLI first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    color = style.use_color()
    project = project_root(start_dir or Path.cwd())
    audit = plugin_reconcile.audit_plugins(workspace_root)
    label_map = plugin_reconcile.label_to_settings(workspace_root)
    specs = active_specs_for_dir(audit, label_map, project)
    if not specs:
        print("no plugin active for this directory — nothing to load into cortex.")
        return 0
    resolved = [resolve_entry(spec) for spec in specs]

    if yes:
        selected = resolved
    else:
        if not sys.stdin.isatty():
            print(
                "Non-interactive shell — pass --yes to launch without the checkbox.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        # la validation n'informe que la ligne de la case à cocher — sans sélecteur, on ne
        # lance aucun `cortex plugin validate`.
        validations = validate_entries(resolved)
        entries = [replace(entry, issues=validations[entry.spec]) for entry in resolved]
        selected = pick_entries(entries, picker=picker)
    if not selected:
        print("nothing selected")
        return 0

    print(render_plan(selected, project))
    if dry_run:
        dirs = [entry.install_path for entry in selected if entry.install_path]
        print(
            style.paint(f"$ {shlex.join(cortex_command(dirs))}", style.DIM, color=color)
        )
        return 0
    if not plugin_enable.confirm(yes=yes, prompt="Launch cortex? [y/N] "):
        print("cancelled.")
        return 0
    dirs = [entry.install_path for entry in selected if entry.install_path]
    if not dirs:
        print("no resolvable plugin directory — nothing to launch.")
        return 0
    completed = subprocess.run(
        cortex_command(dirs),
        cwd=project,
        env=cortex_env(os.environ, project),
        check=False,
    )
    return completed.returncode
