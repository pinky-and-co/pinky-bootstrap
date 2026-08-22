"""Distribute the workspace rules — ``rules/<plugin>/`` → ``<target>/.claude/rules/``.

The rules that steer every session used to be generated into ``.claude/rules/`` by an engine that
no longer exists, leaving them in a directory under no version control and with no source. This
module is the replacement path: the rules live here, in git, and are copied out.

Rules can't travel packaged inside a plugin (the format doesn't exist yet) — this module simulates
the behaviour that WOULD have if they could: a ``rules/<plugin_name>/`` subdirectory here maps to
wherever that plugin is actually installed, resolved from ``~/.claude/plugins/installed_plugins.json``
rather than a single fixed workspace path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .common import AGENTIC_HARNESS_DIR

RULES_DIR = AGENTIC_HARNESS_DIR / "rules"
TARGET_REL = ".claude/rules"
INSTALLED_PLUGINS_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


@dataclass(frozen=True)
class RulesReport:
    """Outcome of one distribution pass — a plan when ``apply=False``, an executed report otherwise.

    Attributes:
        added: Rule filenames with no prior file in the target.
        modified: Rule filenames whose target content differs from the source.
        unchanged: Rule filenames already byte-identical in the target.
        purged: Filenames removed (or, unapplied, slated for removal) from the target — present
            there with no matching source in the rules directory distributed.
    """

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.purged)


def distribute_rules(
    rules_source: Path, target_root: Path, *, apply: bool = True
) -> RulesReport:
    """Diff ``rules_source/*.md`` against ``<target_root>/.claude/rules/``, applying by default.

    The target is a mirror of ``rules_source``: a file with no matching source is purged.

    Args:
        rules_source: Directory of ``.md`` rule files to distribute.
        target_root: Root that gets a ``.claude/`` — a workspace root or a specific repo.
        apply: When False, compute the diff without touching the filesystem — a plan.

    Returns:
        A RulesReport — the plan when ``apply=False``, what was actually done otherwise.

    Raises:
        FileNotFoundError: If ``rules_source`` does not exist.
    """
    if not rules_source.is_dir():
        raise FileNotFoundError(
            f"no rules to distribute: {rules_source} does not exist"
        )

    target = target_root.expanduser().resolve() / TARGET_REL
    if apply:
        target.mkdir(parents=True, exist_ok=True)

    sources = sorted(rules_source.glob("*.md"))
    added: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []
    for src in sources:
        dst = target / src.name
        payload = src.read_text(encoding="utf-8")
        if dst.exists():
            # Comparer le contenu plutôt que réécrire : la cible n'est pas versionnée, donc une
            # réécriture systématique changerait la mtime sans qu'aucun diff ne le justifie.
            if dst.read_text(encoding="utf-8") == payload:
                unchanged.append(src.name)
                continue
            modified.append(src.name)
        else:
            added.append(src.name)
        if apply:
            dst.write_text(payload, encoding="utf-8")

    owned = {src.name for src in sources}
    purged: list[str] = []
    if target.is_dir():
        for f in sorted(target.glob("*.md")):
            if f.name not in owned:
                purged.append(f.name)
                if apply:
                    f.unlink()

    return RulesReport(
        added=added, modified=modified, unchanged=unchanged, purged=purged
    )


def resolve_targets_for_plugin(plugin_name: str, workspace_root: Path) -> list[Path]:
    """Every directory ``plugin_name``'s rules should land in.

    One target per ``installed_plugins.json`` entry whose key (before the ``@``) matches
    ``plugin_name``: ``workspace_root`` for a ``user``-scope install, that entry's ``projectPath``
    for anything else. Empty list if the plugin was never installed on this machine.
    """
    if not INSTALLED_PLUGINS_PATH.is_file():
        return []
    data = json.loads(INSTALLED_PLUGINS_PATH.read_text(encoding="utf-8"))
    targets: list[Path] = []
    for key, entries in data.get("plugins", {}).items():
        if key.split("@", 1)[0] != plugin_name:
            continue
        for entry in entries:
            if entry.get("scope") == "user":
                targets.append(workspace_root)
            elif entry.get("projectPath"):
                targets.append(Path(entry["projectPath"]))
    return targets


def discover_plugin_rule_dirs() -> list[Path]:
    """Every ``rules/<plugin>/`` subdirectory this repo carries — one per plugin with rules to ship."""
    if not RULES_DIR.is_dir():
        return []
    return sorted(p for p in RULES_DIR.iterdir() if p.is_dir())


def distribute_all_plugin_rules(
    workspace_root: Path, *, apply: bool = True
) -> dict[str, dict[Path, RulesReport]]:
    """Distribute every ``rules/<plugin>/`` to its resolved targets.

    Keyed by plugin name, then by target path. A plugin never installed on this machine still
    appears in the result with an empty target dict — visible as "nothing to do", not silently
    dropped.
    """
    result: dict[str, dict[Path, RulesReport]] = {}
    for plugin_dir in discover_plugin_rule_dirs():
        plugin_name = plugin_dir.name
        targets = resolve_targets_for_plugin(plugin_name, workspace_root)
        result[plugin_name] = {
            target: distribute_rules(plugin_dir, target, apply=apply)
            for target in targets
        }
    return result


def print_rules_report(report: RulesReport, workspace: Path) -> None:
    """Print a distribution plan or report — additions, modifications, deletions, unchanged count.

    Args:
        report: Result of :func:`distribute_rules`.
        workspace: Root the rules target (or targeted).
    """
    print(f"rules → {workspace / TARGET_REL}")
    if not report.has_changes:
        print(f"  nothing to do — {len(report.unchanged)} unchanged")
        return
    if report.added:
        print(f"\n➕ added ({len(report.added)})")
        for name in report.added:
            print(f"    {name}")
    if report.modified:
        print(f"\n🔄 modified ({len(report.modified)})")
        for name in report.modified:
            print(f"    {name}")
    if report.purged:
        print(f"\n🗑️ removed ({len(report.purged)}) — no source left")
        for name in report.purged:
            print(f"    {name}")
    print(f"\n  unchanged: {len(report.unchanged)}")


def print_all_plugin_rules_report(result: dict[str, dict[Path, RulesReport]]) -> None:
    """Print a distribution plan or report for every plugin/target pair from
    :func:`distribute_all_plugin_rules`."""
    for plugin_name, by_target in result.items():
        if not by_target:
            print(f"\n=== {plugin_name} — not installed on this machine, skipped ===")
            continue
        for target, report in by_target.items():
            print(f"\n=== {plugin_name} ===")
            print_rules_report(report, target)
