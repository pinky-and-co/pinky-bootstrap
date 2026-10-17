"""setup/plugin_scope.py — which directories a plugin gets enabled at.

`enabledPlugins` resolves per git-repo-root, not always user-level — the project's own
`.claude/settings.json` and every ancestor's (a group directory like `pinky-lib/`, the
workspace root) all apply to a session opened in that repo, the nearest scope carrying the key
winning, user scope last. A plugin can be enabled at the workspace root, at a group directory
(`pinky-lib/` — not itself a git repo, several repos nested under it), or at one specific repo,
or several of these at once.

The wizard picks those targets; the enable itself is `claude plugin install --scope project` run
from each target (`plugin_install.enable_at_project`), never a hand-rolled `enabledPlugins` merge —
Claude Code's own command writes `<target>/.claude/settings.json` and the registry entry together.
User scope is the other branch: the caller installs there (`plugin_install.install_plugin_files`)
only when the user picks it.

The wizard only *picks and enables project targets*. It is asked before anything is downloaded, so
a wizard refusal leaves nothing behind.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import plugin_install, style

_DEPTH_LABELS = {
    0: "workspace root",
    1: "group",
    2: "repo",
}

# A marker file at a directory's own root — not a name pinned to any one workspace (e.g. a
# read-only backup mount) — excludes it and everything below it from the scan. `_collect` never
# reads its content; presence alone is the signal.
IGNORE_MARKER = ".pinky-ignore"


def _is_repo(p: Path) -> bool:
    """Whether `p` is the root of a git repo."""
    return (p / ".git").exists()


def _is_ignored(p: Path) -> bool:
    """Whether `p` carries `IGNORE_MARKER` at its own root — a read-only backup mount or
    anything else the workspace owner wants the scan to never descend into or list."""
    return (p / IGNORE_MARKER).exists()


def _collect(root: Path) -> tuple[list[Path], list[Path]]:
    """Recursively partition `root`'s subtree into groups and repos.

    A repo is pruned once found — its own subtree is never descended into. Dotfile dirs and any
    dir carrying `IGNORE_MARKER` are excluded (the marked dir itself and its whole subtree —
    checked before the repo test, so a marked repo is skipped too). Depth is unbounded: a group
    at any nesting level is included as long as a repo exists somewhere below it.
    """
    groups: list[Path] = []
    repos: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if _is_ignored(p):
            continue
        if _is_repo(p):
            repos.append(p)
            continue  # élagage : repo, rien à descendre en dessous
        sub_groups, sub_repos = _collect(p)
        if sub_repos:
            groups.append(p)  # au moins un repo quelque part dans le sous-arbre
        groups.extend(sub_groups)
        repos.extend(sub_repos)
    return groups, repos


def list_targets_at_depth(workspace_root: Path, depth: int) -> list[Path]:
    """Eligible install targets at `depth` under `workspace_root`.

    - 0: the workspace root itself.
    - 1: every directory, at any nesting level, that has at least one repo
      somewhere in its subtree (a "group") — repos themselves excluded.
    - 2: every directory that is itself a git repo (`.git` present), at any
      nesting level.
    """
    if depth == 0:
        return [workspace_root]
    groups, repos = _collect(workspace_root)
    if depth == 1:
        return groups
    if depth == 2:
        return repos
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
    install_path: Path | None = None,
) -> list[Path]:
    """Interactive scope picker: Q1 (user/project) -> Q2 (depth, project only) -> Q3 (which
    targets at that depth — one or several) -> enable the plugin at each. Returns the roots it
    enabled the plugin at.

    User scope: nothing to do here but report it (`[Path.home()]`) — the caller installs there.
    Project scope: `plugin_install.enable_at_project` per target, which also downloads the plugin.

    `skip_scope_question`: the caller already asked `user` vs `project` and got `project` (the
    `pinky claude-plugin reconcile` loop, whose own per-plugin prompt covers Q1) — go straight to
    the depth+targets picker. Never returns `[Path.home()]` on this path.

    `install_path`: the plugin's already-fetched files (caller resolves it — `resolve_install_path`
    needs a populated registry that a wizard call site does not always have to hand). When it
    ships a language server (`plugin_install.ships_lsp_server`), `ENABLE_LSP_TOOL` gets wired at
    every scope this call enables — the same gap `statusLine` closes for a status-line plugin.
    `None` (every pre-existing caller) skips this step, never guesses.

    Never guesses in a non-interactive shell (no tty) — errors instead, same discipline
    as the `--rules` confirmation flow in `setup/cli.py`. The placement this wizard does
    is a decision, not a value some flag carries: no option replaces the questions, so
    the refusal names the need (a terminal), never a flag.
    """
    if not sys.stdin.isatty():
        print(
            "Non-interactive shell — the placement wizard needs a terminal.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    color = style.use_color()
    ships_lsp = install_path is not None and plugin_install.ships_lsp_server(
        install_path
    )

    if not skip_scope_question:
        scope = (
            input(
                style.paint(
                    "Scope — (u)ser or (p)roject? [u/p]: ", style.BOLD, color=color
                )
            )
            .strip()
            .lower()
        )
        if scope == "u":
            # l'appelant installe au scope user : rien à écrire ici.
            if ships_lsp:
                plugin_install.ensure_lsp_tool_enabled()
            return [Path.home()]
        if scope != "p":
            print(f"Unknown scope: {scope!r}", file=sys.stderr)
            raise SystemExit(1)

    depth_prompt = " / ".join(f"{d}={label}" for d, label in _DEPTH_LABELS.items())
    depth_answer = input(
        style.paint(f"Depth — {depth_prompt}: ", style.BOLD, color=color)
    ).strip()
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
    choice = input(
        style.paint(
            "Pick one or more targets (indices, space-separated): ",
            style.BOLD,
            color=color,
        )
    ).strip()
    try:
        picked = _parse_indices(choice, len(targets))
    except ValueError as exc:
        print(f"Invalid choice: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    roots = [targets[i] for i in picked]
    tick = style.paint("✓", style.GREEN, color=color)
    for root in roots:
        plugin_install.enable_at_project(plugin_id, root, marketplace)
        print(f"{tick} enabled {plugin_id} at {root}")
    # `ENABLE_LSP_TOOL` is a single user-scope key — write it once, not once per target.
    if ships_lsp and roots:
        plugin_install.ensure_lsp_tool_enabled()
    return roots
