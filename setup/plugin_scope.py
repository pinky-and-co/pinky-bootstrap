"""setup/plugin_scope.py — where a plugin/marketplace gets enabled.

`enabledPlugins` resolves per git repo root, not always user-level (ADR-0001, corrigé 2026-08-21) —
`.claude/settings.json` at a directory applies to any session started under it, crossing nested
`.git` boundaries on the way down (not just within one repo). A plugin can therefore be enabled at
the workspace root, at a group directory (`pinky-lib/` — not itself a git repo, several repos
nested under it), or at one specific repo — same merge logic at every level.

`enable_plugin`'s `root` is `Path.home()` for user scope, or any project/group/repo directory for
project scope — the merge target is always `<root>/.claude/settings.json`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import state_file

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


def _settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def enable_plugin(root: Path, plugin_id: str, marketplace: str | None = None) -> None:
    """Merge `enabledPlugins[key] = True` into `<root>/.claude/settings.json`.

    Never overwrites the file — reads what's there (if anything) and merges only this one key,
    same discipline as the rest of this repo's settings.json writers. Records the write in the
    installer's ledger (`setup.state_file`).
    """
    key = f"{plugin_id}@{marketplace}" if marketplace else plugin_id
    settings_path = _settings_path(root)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.loads(settings_path.read_text(encoding="utf-8"))
        if settings_path.is_file()
        else {}
    )
    enabled = data.setdefault("enabledPlugins", {})
    enabled[key] = True
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    state_file.record_posed(
        f"enabledPlugins:{key}@{root}", path=str(settings_path), value="true"
    )


def run_marketplace_wizard(
    workspace_root: Path, plugin_id: str, marketplace: str | None = None
) -> Path:
    """Interactive scope picker: Q1 (user/project) -> Q2 (depth, project only) -> Q3 (which
    target at that depth) -> `enable_plugin()`. Returns the root it enabled the plugin at.

    Never guesses in a non-interactive shell (no tty) — errors instead, same discipline as the
    `--rules` confirmation flow in `setup/cli.py`.
    """
    if not sys.stdin.isatty():
        print(
            "Non-interactive shell — plugin scope needs a terminal to ask.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    scope = input("Scope — (u)ser or (p)roject? [u/p]: ").strip().lower()
    if scope == "u":
        root = Path.home()
    elif scope == "p":
        depth_prompt = " / ".join(f"{d}={label}" for d, label in _DEPTH_LABELS.items())
        depth_answer = input(f"Depth — {depth_prompt}: ").strip()
        try:
            depth = int(depth_answer)
        except ValueError:
            print(f"Unknown depth: {depth_answer!r}", file=sys.stderr)
            raise SystemExit(1) from None
        targets = list_targets_at_depth(workspace_root, depth)
        if not targets:
            print(f"No target found at depth {depth}.", file=sys.stderr)
            raise SystemExit(1)
        for i, target in enumerate(targets):
            print(f"  {i}) {target.name}")
        choice = input("Pick a target (index): ").strip()
        try:
            root = targets[int(choice)]
        except (ValueError, IndexError):
            print(f"Invalid choice: {choice!r}", file=sys.stderr)
            raise SystemExit(1) from None
    else:
        print(f"Unknown scope: {scope!r}", file=sys.stderr)
        raise SystemExit(1)

    enable_plugin(root, plugin_id, marketplace)
    print(f"Enabled {plugin_id} at {root}")
    return root
