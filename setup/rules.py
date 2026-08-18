"""Distribute the workspace rules — ``rules/core/`` → ``<workspace>/.claude/rules/``.

The rules that steer every session used to be generated into ``.claude/rules/`` by an engine that
no longer exists, leaving them in a directory under no version control and with no source. This
module is the replacement path: the rules live here, in git, and are copied out.

**Orphans are deliberately left alone, and that is temporary.** A rule already sitting in the
target that this repo does not (yet) own is reported, never deleted — the migration moves rules
over one at a time, and purging on the first pass would wipe the ones not yet migrated. Once they
all live here, the distribution is expected to purge instead: the target becomes a mirror, and a
file with no source in ``rules/core/`` is drift. Do not read the current tolerance as the intended
end state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .common import SCRIPT_DIR

RULES_DIR = SCRIPT_DIR / "rules"
CORE_RULES_DIR = RULES_DIR / "core"
TARGET_REL = ".claude/rules"


@dataclass(frozen=True)
class RulesReport:
    """Outcome of one distribution pass.

    Attributes:
        written: Rule filenames created or updated in the target.
        unchanged: Rule filenames already byte-identical in the target.
        orphans: Filenames present in the target with no source in ``rules/core/`` — not yet
            migrated, left untouched on purpose.
    """

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)


def distribute_rules(workspace: Path) -> RulesReport:
    """Copy every ``rules/core/*.md`` into ``<workspace>/.claude/rules/``.

    Overwrites by filename and deletes nothing. The target directory is created if absent.

    Args:
        workspace: Workspace root — the directory holding ``.claude/``.

    Returns:
        A RulesReport listing what was written, what was already current, and which target files
        have no source here yet.

    Raises:
        FileNotFoundError: If ``rules/core/`` does not exist in this repo.
    """
    if not CORE_RULES_DIR.is_dir():
        raise FileNotFoundError(
            f"no rules to distribute: {CORE_RULES_DIR} does not exist"
        )

    target = workspace.expanduser().resolve() / TARGET_REL
    target.mkdir(parents=True, exist_ok=True)

    report = RulesReport()
    sources = sorted(CORE_RULES_DIR.glob("*.md"))
    for src in sources:
        dst = target / src.name
        payload = src.read_text(encoding="utf-8")
        # Comparer le contenu plutôt que réécrire : la cible n'est pas versionnée, donc une
        # réécriture systématique changerait la mtime sans qu'aucun diff ne le justifie.
        if dst.exists() and dst.read_text(encoding="utf-8") == payload:
            report.unchanged.append(src.name)
            continue
        dst.write_text(payload, encoding="utf-8")
        report.written.append(src.name)

    owned = {src.name for src in sources}
    report.orphans.extend(
        sorted(f.name for f in target.glob("*.md") if f.name not in owned)
    )
    return report


def print_rules_report(report: RulesReport, workspace: Path) -> None:
    """Print a distribution report, orphan count included.

    The orphan count is the migration's progress counter: it drops by one each time a rule moves
    into ``rules/core/``, and reaching zero is what makes purging safe to turn on.

    Args:
        report: Result of :func:`distribute_rules`.
        workspace: Workspace root the rules were written to.
    """
    print(f"rules → {workspace / TARGET_REL}")
    print(
        f"  écrites   : {len(report.written)}"
        + (f"  ({', '.join(report.written)})" if report.written else "")
    )
    print(f"  inchangées: {len(report.unchanged)}")
    if report.orphans:
        print(
            f"  orphelines: {len(report.orphans)} — pas encore migrées, laissées en place"
        )
        for name in report.orphans:
            print(f"      {name}")
