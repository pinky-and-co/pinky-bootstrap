"""Distribute the workspace rules — ``rules/core/`` → ``<workspace>/.claude/rules/``.

The rules that steer every session used to be generated into ``.claude/rules/`` by an engine that
no longer exists, leaving them in a directory under no version control and with no source. This
module is the replacement path: the rules live here, in git, and are copied out.

The target is a mirror of ``rules/core/``: a file with no matching source is drift and is purged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .common import AGENTIC_HARNESS_DIR

RULES_DIR = AGENTIC_HARNESS_DIR / "rules"
CORE_RULES_DIR = RULES_DIR / "core"
TARGET_REL = ".claude/rules"


@dataclass(frozen=True)
class RulesReport:
    """Outcome of one distribution pass — a plan when ``apply=False``, an executed report otherwise.

    Attributes:
        added: Rule filenames with no prior file in the target.
        modified: Rule filenames whose target content differs from the source.
        unchanged: Rule filenames already byte-identical in the target.
        purged: Filenames removed (or, unapplied, slated for removal) from the target — present
            there with no matching source in ``rules/core/``.
    """

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.purged)


def distribute_rules(workspace: Path, *, apply: bool = True) -> RulesReport:
    """Diff ``rules/core/*.md`` against ``<workspace>/.claude/rules/``, applying the diff by default.

    The target is a mirror of ``rules/core/``: a file with no matching source is purged.

    Args:
        workspace: Workspace root — the directory holding ``.claude/``.
        apply: When False, compute the diff without touching the filesystem — a plan.

    Returns:
        A RulesReport — the plan when ``apply=False``, what was actually done otherwise.

    Raises:
        FileNotFoundError: If ``rules/core/`` does not exist in this repo.
    """
    if not CORE_RULES_DIR.is_dir():
        raise FileNotFoundError(
            f"no rules to distribute: {CORE_RULES_DIR} does not exist"
        )

    target = workspace.expanduser().resolve() / TARGET_REL
    if apply:
        target.mkdir(parents=True, exist_ok=True)

    sources = sorted(CORE_RULES_DIR.glob("*.md"))
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


def print_rules_report(report: RulesReport, workspace: Path) -> None:
    """Print a distribution plan or report — additions, modifications, deletions, unchanged count.

    Args:
        report: Result of :func:`distribute_rules`.
        workspace: Workspace root the rules target (or targeted).
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
        print(f"\n🗑️ removed ({len(report.purged)}) — no source left in rules/core/")
        for name in report.purged:
            print(f"    {name}")
    print(f"\n  unchanged: {len(report.unchanged)}")
