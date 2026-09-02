"""setup/plugin_scope.py — which directories a plugin gets enabled at.

`enabledPlugins` resolves per directory, not always user-level (ADR-0001, corrigé 2026-08-21) —
`.claude/settings.json` at a directory applies to any session started under it, crossing nested
`.git` boundaries on the way down. A plugin can therefore be enabled at the workspace root, at a
group directory (`pinky-lib/` — not itself a git repo, several repos nested under it), or at one
specific repo, or several of these at once.

The wizard picks those targets; the enable itself is `claude plugin install --scope project` run
from each target (`plugin_install.enable_at_project`), never a hand-rolled `enabledPlugins` merge —
Claude Code's own command writes `<target>/.claude/settings.json` and the registry entry together
(measured 2026-09-02). User scope is the other branch: the plugin the user keeps global stays where
`install_plugin_files` already enabled it.

The wizard only *picks and enables targets*; the user-scope lifecycle (dropping the fetch-time
transient enable) is the caller's — it captured `is_user_enabled` before the fetch and knows
whether that is safe, and it must also undo on a wizard `SystemExit`, which this function cannot.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import plugin_install

_DEPTH_LABELS = {
    0: "workspace root",
    1: "top-level dir (repo or group)",
    2: "repo nested under a group",
}


def list_targets_at_depth(workspace_root: Path, depth: int) -> list[Path]:
    """Eligible install targets at `depth` under `workspace_root`.

    - 0: the workspace root itself.
    - 1: every top-level directory (a repo directly, or a group of repos) — dotfile dirs excluded.
    - 2: repos nested one level under a depth-1 GROUP only (a depth-1 dir that is itself a repo has
      nothing further to descend into).
    """
    if depth == 0:
        return [workspace_root]
    if depth == 1:
        return [
            p
            for p in sorted(workspace_root.iterdir())
            if p.is_dir() and not p.name.startswith(".")
        ]
    if depth == 2:
        targets: list[Path] = []
        for group in list_targets_at_depth(workspace_root, 1):
            if (group / ".git").exists():
                continue  # a repo itself, not a group — nothing nested to list
            targets += [
                p
                for p in sorted(group.iterdir())
                if p.is_dir() and (p / ".git").exists()
            ]
        return targets
    raise ValueError(f"depth {depth} not supported (0-2)")


def _parse_indices(answer: str, count: int) -> list[int]:
    """Space- or comma-separated 0-based indices, each within [0, count). Raises on anything else
    so the wizard errors rather than enabling a plugin at a target the user did not name."""
    tokens = answer.replace(",", " ").split()
    if not tokens:
        raise ValueError("no target picked")
    picked = []
    for tok in tokens:
        idx = int(tok)  # ValueError propagates — same discipline as the depth answer
        if not 0 <= idx < count:
            raise ValueError(f"index {idx} out of range 0-{count - 1}")
        picked.append(idx)
    return picked


def run_marketplace_wizard(
    workspace_root: Path,
    plugin_id: str,
    marketplace: str | None = None,
    *,
    skip_scope_question: bool = False,
) -> list[Path]:
    """Interactive scope picker: Q1 (user/project) -> Q2 (depth, project only) -> Q3 (which
    targets at that depth — one or several) -> enable the plugin at each. Returns the roots it
    enabled the plugin at.

    User scope: the plugin is already enabled there by `install_plugin_files` — nothing to do but
    report it (`[Path.home()]`). Project scope: `plugin_install.enable_at_project` per target;
    the caller then drops the fetch-time user-scope enable if it was not there before.

    `skip_scope_question`: the caller already asked `user` vs `project` and got `project` (the
    `pinky plugins reconcile --apply` loop, whose own per-plugin prompt covers Q1) — go straight to
    the depth+targets picker. Never returns `[Path.home()]` on this path.

    Never guesses in a non-interactive shell (no tty) — errors instead, same discipline as the
    `--rules` confirmation flow in `setup/cli.py`.
    """
    if not sys.stdin.isatty():
        print(
            "Non-interactive shell — plugin scope needs a terminal to ask.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not skip_scope_question:
        scope = input("Scope — (u)ser or (p)roject? [u/p]: ").strip().lower()
        if scope == "u":
            # déjà activé au scope user par install_plugin_files — rien à réécrire.
            return [Path.home()]
        if scope != "p":
            print(f"Unknown scope: {scope!r}", file=sys.stderr)
            raise SystemExit(1)

    depth_prompt = " / ".join(f"{d}={label}" for d, label in _DEPTH_LABELS.items())
    depth_answer = input(f"Depth — {depth_prompt}: ").strip()
    try:
        depth = int(depth_answer)
    except ValueError:
        print(f"Unknown depth: {depth_answer!r}", file=sys.stderr)
        raise SystemExit(1) from None
    try:
        targets = list_targets_at_depth(workspace_root, depth)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
    if not targets:
        print(f"No target found at depth {depth}.", file=sys.stderr)
        raise SystemExit(1)

    for i, target in enumerate(targets):
        print(f"  {i}) {target.name}")
    choice = input("Pick one or more targets (indices, space-separated): ").strip()
    try:
        picked = _parse_indices(choice, len(targets))
    except ValueError as exc:
        print(f"Invalid choice: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    roots = [targets[i] for i in picked]
    for root in roots:
        plugin_install.enable_at_project(plugin_id, root, marketplace)
        print(f"Enabled {plugin_id} at {root}")
    return roots
