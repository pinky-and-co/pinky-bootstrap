"""Distribute the workspace rules — ``rules/<plugin>/`` → ``<target>/.claude/rules/``.

The rules that steer every session used to be generated into ``.claude/rules/`` by an engine that
no longer exists, leaving them in a directory under no version control and with no source. This
module is the replacement path: the rules live here, in git, and are copied out.

Rules can't travel packaged inside a plugin (the format doesn't exist yet) — this module simulates
the behaviour that WOULD have if they could: a ``rules/<plugin_name>/`` subdirectory here maps to
wherever that plugin is actually installed, resolved from ``~/.claude/plugins/installed_plugins.json``
rather than a single fixed workspace path.

A source rule carrying a ``_load_conditions`` frontmatter key is distributed lazily: a short stub
in ``.claude/rules/`` (same ``paths:``, one Read instruction) and the body in
``.claude/rules-content/``. The stub is a fixed frame around the rule author's free clause(s) —
accepted form: see `_validated_conditions`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import style
from .common import AGENTIC_HARNESS_DIR

RULES_DIR = AGENTIC_HARNESS_DIR / "rules"
TARGET_REL = ".claude/rules"
CONTENT_REL = ".claude/rules-content"
INSTALLED_PLUGINS_PATH = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
# A user override has RULES_DIR's "<plugin>/<file>.md" shape.
USER_RULES_DIR = Path.home() / ".claude" / "rules"
EXCLUDE_SUFFIX = ".md.exclude"


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


_STUB_TEMPLATE = (
    "Your FIRST action, {conditions}, MUST be to `Read` `{content_path}` in full.\n"
)


def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """(frontmatter lines without the ``---`` fences, body) — ``([], text)`` with no frontmatter.

    A fence is exactly ``---`` once trailing whitespace is stripped; a BOM before the opening
    fence is ignored.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").rstrip() != "---":
        return [], text
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return lines[1:i], "".join(lines[i + 1 :])
    return [], text


def _key_block(front: list[str], key: str) -> list[str] | None:
    """The raw lines of `key:` and its indented / ``- `` continuation lines, None when absent."""
    for i, line in enumerate(front):
        if line.startswith(f"{key}:"):
            block = [line]
            for follow in front[i + 1 :]:
                if not follow.strip() or follow.lstrip().startswith("#"):
                    continue
                if follow[0] in " \t" or follow.startswith("- "):
                    block.append(follow)
                else:
                    break
            return block
    return None


def _validated_conditions(rule: str, block: list[str]) -> list[str]:
    """The `_load_conditions` items of a rule, each checked against the accepted form.

    Accepted form of one item — a free clause that completes "Your FIRST action, …, MUST be to
    Read …"; e.g. `if you are fixing a bug or extending code`:

    - non-blank once stripped, on a single line (an indented continuation line is refused);
    - no trailing ``,`` ``.`` ``;`` ``:`` — the frame adds its own punctuation around the clause;
    - no leading YAML indicator ``>`` ``|`` ``&`` ``*`` ``!`` (folded, anchored or tagged
      scalars are not supported);
    - no backtick (it would break the stub's own quoting).

    The list must be non-empty, and written block-style: an inline value after the key is
    refused. Full-line ``#`` comments are skipped, an `` # note`` suffix is stripped, and each
    item is stripped again after unquoting.

    Args:
        rule: The rule filename, named in the error.
        block: The raw `_load_conditions:` line and its list lines.

    Returns:
        The conditions, unquoted.

    Raises:
        ValueError: Naming the rule file and the offending condition.
    """
    if re.sub(r"\s+#.*$", "", block[0].split(":", 1)[1]).strip():
        raise ValueError(f"{rule}: _load_conditions: block-style list required")
    conditions = []
    for line in block[1:]:
        item = line.strip()
        if not item.startswith("-"):
            raise ValueError(
                f"{rule}: invalid _load_conditions line {item!r} — "
                "a continuation line is not supported, one '- item' per line"
            )
        item = item[1:].strip()
        quoted = re.fullmatch(r"""(["'])(.*)\1(?:\s+#.*)?""", item)
        conditions.append(
            (quoted[2] if quoted else re.sub(r"\s+#.*$", "", item)).strip()
        )
    if not conditions:
        raise ValueError(f"{rule}: _load_conditions is empty")
    for cond in conditions:
        problem = (
            "blank item"
            if not cond
            else "ends with punctuation, the frame adds its own comma"
            if cond[-1] in ",.;:"
            else "starts with a YAML indicator (> | & * !), not supported"
            if cond[0] in ">|&*!"
            else "contains a backtick"
            if "`" in cond
            else None
        )
        if problem:
            raise ValueError(
                f"{rule}: invalid _load_conditions entry {cond!r} — {problem}"
            )
    return conditions


def _render_rule(name: str, text: str, content_path: Path) -> tuple[str, str | None]:
    """(text of `.claude/rules/<name>`, text of `.claude/rules-content/<name>` or None).

    A source without `_load_conditions` is copied as-is, whatever its first line. With it, the rules file is a regenerated
    stub (the source's `paths:` block + the Read instruction naming `content_path`, absolute: a
    session started in a child directory loads this ancestor's rules) and the content file is the
    body.

    Args:
        name: The rule filename.
        text: The source rule text.
        content_path: Resolved absolute path of the rule's `.claude/rules-content/` file.

    Returns:
        The stub (or the source verbatim) and the content body (None when not lazy).

    Raises:
        ValueError: The text carries a `_load_conditions:` line but its frontmatter does not
            parse — it would otherwise be copied eagerly, defeating the lazy load.
    """
    front, body = _split_frontmatter(text)
    if (
        not front
        and body == text
        and any(line.startswith("_load_conditions:") for line in text.splitlines())
    ):
        raise ValueError(f"{name}: unclosed frontmatter")
    block = _key_block(front, "_load_conditions")
    if block is None:
        return text, None
    conditions = " or ".join(_validated_conditions(name, block))
    paths = _key_block(front, "paths")
    stub = "---\n" + "".join(paths) + "---\n\n" if paths else ""
    stub += _STUB_TEMPLATE.format(conditions=conditions, content_path=content_path)
    return stub, body.lstrip("\r\n")


def _distribute_sources(
    sources: Mapping[str, Path],
    target_root: Path,
    *,
    apply: bool = True,
    sibling_owned: frozenset[str] = frozenset(),
) -> RulesReport:
    """Diff `sources` (filename -> file to copy) against `<target_root>/.claude/rules/`, applying
    by default — the mechanism `distribute_rules` (one plain directory) and the two-level
    shipped+user merge (`_merged_sources`) both funnel through, so the diff/purge logic is written
    once.

    A source carrying `_load_conditions` lands as a stub in `.claude/rules/` plus its body in
    `.claude/rules-content/` (see `_render_rule`); it is "modified" when either differs.

    The target is a mirror of `sources`: a file with no matching entry is purged — unless it is in
    `sibling_owned`, i.e. owned by another plugin that resolves to the same target. Without that
    exemption, two plugins landing in one `.claude/rules/` purge each other's rules on alternate
    passes. `.claude/rules-content/` is mirrored the same way, owned by the lazy sources only.
    """
    base = target_root.expanduser().resolve() / ".claude"
    target = base / "rules"
    content_dir = base / "rules-content"

    # Render everything first: an invalid rule raises before anything is written.
    rendered = {
        name: _render_rule(name, src.read_text(encoding="utf-8"), content_dir / name)
        for name, src in sorted(sources.items())
    }
    if apply:
        target.mkdir(parents=True, exist_ok=True)

    added: list[str] = []
    modified: list[str] = []
    unchanged: list[str] = []
    for name, (stub, content) in rendered.items():
        dst = target / name
        cdst = content_dir / name
        # Comparer le contenu plutôt que réécrire : la cible n'est pas versionnée, donc une
        # réécriture systématique changerait la mtime sans qu'aucun diff ne le justifie.
        stub_same = dst.exists() and dst.read_text(encoding="utf-8") == stub
        content_same = (
            not cdst.exists()
            if content is None
            else cdst.exists() and cdst.read_text(encoding="utf-8") == content
        )
        if stub_same and content_same:
            unchanged.append(name)
            continue
        (modified if dst.exists() else added).append(name)
        if apply:
            # Content first: a crash never leaves a stub pointing at a missing file. A stale
            # content file (lazy → eager) is removed by the mirror pass below.
            if content is not None and not content_same:
                content_dir.mkdir(parents=True, exist_ok=True)
                cdst.write_text(content, encoding="utf-8")
            if not stub_same:
                dst.write_text(stub, encoding="utf-8")

    owned = set(sources) | sibling_owned
    lazy = {name for name, (_, content) in rendered.items() if content is not None}
    purged: list[str] = []
    if target.is_dir():
        for f in sorted(target.glob("*.md")):
            if f.name not in owned:
                purged.append(f.name)
                if apply:
                    f.unlink()
    if content_dir.is_dir():
        for f in sorted(content_dir.glob("*.md")):
            if f.name not in lazy | sibling_owned:
                # A name with a source here is reported as modified, not as "no source left".
                if f.name not in owned and f.name not in purged:
                    purged.append(f.name)
                if apply:
                    f.unlink()

    return RulesReport(
        added=added, modified=modified, unchanged=unchanged, purged=purged
    )


def _covered_by_ancestor(target: Path, targets: Iterable[Path]) -> bool:
    """True when another of `targets` is a parent of `target` — Claude Code already loads that
    parent's `.claude/rules/` in any session under it, so a copy here would load twice."""
    return any(other != target and target.is_relative_to(other) for other in targets)


def _withdraw_sources(
    names: Iterable[str], target_root: Path, *, apply: bool = True
) -> RulesReport:
    """Remove only the files named `names` from `<target_root>/.claude/rules/` — never a mirror
    purge: a covered target may hold its own hand-written rules, which no plugin owns."""
    target = target_root.expanduser().resolve() / TARGET_REL
    content = target_root.expanduser().resolve() / CONTENT_REL
    purged = sorted(
        name
        for name in names
        if (target / name).is_file() or (content / name).is_file()
    )
    if apply:
        for name in purged:
            (target / name).unlink(missing_ok=True)
            (content / name).unlink(missing_ok=True)
    return RulesReport(purged=purged)


def distribute_rules(
    rules_source: Path,
    target_root: Path,
    *,
    apply: bool = True,
    sibling_owned: frozenset[str] = frozenset(),
) -> RulesReport:
    """Diff ``rules_source/*.md`` against ``<target_root>/.claude/rules/``, applying by default.

    Args:
        rules_source: Directory of ``.md`` rule files to distribute.
        target_root: Root that gets a ``.claude/`` — a workspace root or a specific repo.
        apply: When False, compute the diff without touching the filesystem — a plan.
        sibling_owned: Filenames owned by a co-resident plugin at this target — never purged,
            never reported, even with no matching source here.

    Returns:
        A RulesReport — the plan when ``apply=False``, what was actually done otherwise.

    Raises:
        FileNotFoundError: If ``rules_source`` does not exist.
    """
    if not rules_source.is_dir():
        raise FileNotFoundError(
            f"no rules to distribute: {rules_source} does not exist"
        )
    sources = {src.name: src for src in rules_source.glob("*.md")}
    return _distribute_sources(
        sources, target_root, apply=apply, sibling_owned=sibling_owned
    )


def resolve_user_rules_dir(explicit: Path | None = None) -> Path:
    """The user's rules override root — `explicit` (a CLI `--rules-dir`) or `USER_RULES_DIR`."""
    return explicit if explicit is not None else USER_RULES_DIR


def _merged_sources(plugin_dir: Path, user_plugin_dir: Path) -> dict[str, Path]:
    """One plugin's rule files after the user's overlay: `<user_plugin_dir>/<name>.md` adds a rule
    or replaces a shipped one of the same name, `<user_plugin_dir>/<name>.md.exclude` (an empty
    marker, never itself globbed as a rule) drops a shipped rule from distribution.
    """
    sources = (
        {src.name: src for src in plugin_dir.glob("*.md")}
        if plugin_dir.is_dir()
        else {}
    )
    if not user_plugin_dir.is_dir():
        return sources
    for marker in user_plugin_dir.glob(f"*{EXCLUDE_SUFFIX}"):
        sources.pop(marker.name.removesuffix(".exclude"), None)
    for src in user_plugin_dir.glob("*.md"):
        sources[src.name] = src
    return sources


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


@dataclass(frozen=True, eq=False)
class PluginRulesResult(Mapping[Path, RulesReport]):
    """A plugin's distribution outcome: its `RulesReport` at each resolved target directory.

    A read-only mapping — supports `[target]`, `.items()`, `.keys()`, truthiness and `== {}`,
    exactly like the plain `dict` it replaces.
    """

    by_target: dict[Path, RulesReport] = field(default_factory=dict)

    def __getitem__(self, key: Path) -> RulesReport:
        return self.by_target[key]

    def __iter__(self) -> Iterator[Path]:
        return iter(self.by_target)

    def __len__(self) -> int:
        return len(self.by_target)


def distribute_all_plugin_rules(
    workspace_root: Path, *, apply: bool = True, user_rules_dir: Path | None = None
) -> dict[str, PluginRulesResult]:
    """Distribute every ``rules/<plugin>/`` (each merged with its user override, see
    `_merged_sources`) to its resolved targets.

    Keyed by plugin name, then by target path. A plugin never installed on this machine still
    appears in the result with an empty target dict — visible as "nothing to do", not silently
    dropped.

    The per-target mirror purge is scoped to the union of every plugin that resolves to that
    target: a file in ``.claude/rules/`` is purged only when no such plugin has a source for it.

    Args:
        workspace_root: The directory a ``user``-scope plugin's rules resolve to.
        apply: When False, compute the plan without touching the filesystem.
        user_rules_dir: The user's override root (default: `resolve_user_rules_dir()`).

    Returns:
        Reports keyed by plugin name, then by target path.
    """
    user_rules_dir = resolve_user_rules_dir(user_rules_dir)
    plugin_dirs = discover_plugin_rule_dirs()
    # Resolve targets up front: the sibling map below groups plugins by target, and two spellings
    # of one directory (trailing slash, symlink, ``~``) must not land in separate buckets — that
    # revives the mutual-purge bug this scoping fixes.
    targets_by_plugin = {
        d.name: [
            t.expanduser().resolve()
            for t in resolve_targets_for_plugin(d.name, workspace_root)
        ]
        for d in plugin_dirs
    }
    plugins_by_target: dict[Path, list[Path]] = {}
    for plugin_dir in plugin_dirs:
        for target in targets_by_plugin[plugin_dir.name]:
            plugins_by_target.setdefault(target, []).append(plugin_dir)

    result: dict[str, PluginRulesResult] = {}
    for plugin_dir in plugin_dirs:
        by_target: dict[Path, RulesReport] = {}
        my_sources = _merged_sources(plugin_dir, user_rules_dir / plugin_dir.name)
        my_targets = targets_by_plugin[plugin_dir.name]
        for target in my_targets:
            if _covered_by_ancestor(target, my_targets):
                withdrawn = _withdraw_sources(my_sources, target, apply=apply)
                if withdrawn.purged:
                    by_target[target] = withdrawn
                continue
            sibling_owned = frozenset(
                name
                for other in plugins_by_target[target]
                if other != plugin_dir
                for name in _merged_sources(other, user_rules_dir / other.name)
            )
            by_target[target] = _distribute_sources(
                my_sources, target, apply=apply, sibling_owned=sibling_owned
            )
        result[plugin_dir.name] = PluginRulesResult(by_target)
    return result


def rules_report_for_plugin_at_targets(
    plugin_name: str,
    present_targets: Iterable[Path],
    previously_resolved_targets: Iterable[Path],
    workspace_root: Path,
    *,
    apply: bool = True,
    user_rules_dir: Path | None = None,
    active_dirs_by_plugin: Mapping[str, Iterable[Path]] | None = None,
) -> dict[Path, RulesReport]:
    """This plugin's rules at exactly the targets an `enable`/`disable` action decided, rather
    than a fresh `installed_plugins.json` read — the plan shown before `[y/N]` and the write after
    confirmation must agree, and the registry only reflects the new state once the scope mutation
    (`claude plugin install/uninstall`) has already run.

    `present_targets`: where the plugin ends up enabled (sources distributed there).
    `previously_resolved_targets`: where it was enabled before this action (from the pre-mutation
    audit) — a target dropped from `present_targets` still gets visited here, with no source, so
    its files are purged. Without this, a target that stops resolving for the plugin altogether
    would never be visited again by anything and would keep its stale rule files forever (the
    per-target mirror purge only runs for a target it is actually asked to check).

    `active_dirs_by_plugin`: every OTHER plugin's currently-active directories, keyed by bare
    plugin name, for the sibling-ownership check below. Pass the settings-label-derived directory
    set here (`plugin_enable`'s own audit), not the registry: a plugin enabled through a bare
    `@inline` settings key (no `installed_plugins.json` entry) has no `resolve_targets_for_plugin`
    hit at all, so falling back to the registry here would purge its rules as collateral of an
    unrelated plugin's disable. `None` (a caller with no settings audit at hand) falls back to the
    registry, same as `distribute_all_plugin_rules`.

    A plugin with neither a shipped `rules/<plugin_name>/` directory nor a user override visits no
    target at all — no directory created, no purge run — so naming a plugin that ships no rules
    (`enable`/`disable` on any plugin, rules or not) never touches an unrelated `.claude/rules/`.
    """
    user_rules_dir = resolve_user_rules_dir(user_rules_dir)
    plugin_dir = RULES_DIR / plugin_name
    user_plugin_dir = user_rules_dir / plugin_name
    if not plugin_dir.is_dir() and not user_plugin_dir.is_dir():
        return {}
    my_sources = _merged_sources(plugin_dir, user_plugin_dir)
    present = {t.expanduser().resolve() for t in present_targets}
    all_targets = present | {
        t.expanduser().resolve() for t in previously_resolved_targets
    }

    def _sibling_active_dirs(name: str) -> set[Path]:
        if active_dirs_by_plugin is not None:
            return {p.resolve() for p in active_dirs_by_plugin.get(name, ())}
        return {
            t.expanduser().resolve()
            for t in resolve_targets_for_plugin(name, workspace_root)
        }

    def sibling_owned_at(target: Path) -> frozenset[str]:
        return frozenset(
            name
            for other_dir in discover_plugin_rule_dirs()
            if other_dir.name != plugin_name
            for name in _merged_sources(other_dir, user_rules_dir / other_dir.name)
            if target in _sibling_active_dirs(other_dir.name)
        )

    return {
        target: (
            _withdraw_sources(my_sources, target, apply=apply)
            if target in present and _covered_by_ancestor(target, present)
            else _distribute_sources(
                my_sources if target in present else {},
                target,
                apply=apply,
                sibling_owned=sibling_owned_at(target),
            )
        )
        for target in sorted(all_targets)
    }


def print_rules_report(
    report: RulesReport, workspace: Path, *, color: bool = False
) -> None:
    """Print a distribution plan or report — additions, modifications, deletions, unchanged count,
    what changed in evidence first (`setup/doctor.py`'s own convention, via `setup/style.py`).

    Args:
        report: Result of :func:`distribute_rules`.
        workspace: Root the rules target (or targeted).
        color: Paint added/modified/purged/unchanged the way `setup/doctor.py` does — off by
            default (`style.paint` no-ops then), so a caller that never passes it sees
            byte-identical output.
    """
    print(f"rules → {workspace / TARGET_REL}")
    if not report.has_changes:
        tick = style.paint("✓", style.GREEN, color=color)
        print(f"  {tick} nothing to do — {len(report.unchanged)} unchanged")
        return
    if report.added:
        print(
            style.paint(f"\n➕ added ({len(report.added)})", style.GREEN, color=color)
        )
        for name in report.added:
            print(f"    {name}")
    if report.modified:
        print(f"\n🔄 modified ({len(report.modified)})")
        for name in report.modified:
            print(f"    {name}")
    if report.purged:
        print(
            style.paint(
                f"\n🗑️ removed ({len(report.purged)}) — no source left",
                style.RED_BOLD,
                color=color,
            )
        )
        for name in report.purged:
            print(f"    {name}")
    print(
        f"\n  {style.paint(f'unchanged: {len(report.unchanged)}', style.DIM, color=color)}"
    )


def print_all_plugin_rules_report(
    result: dict[str, PluginRulesResult], *, verbose: bool = False, color: bool = False
) -> None:
    """Print a distribution plan or report for every plugin/target pair from
    :func:`distribute_all_plugin_rules` — a per-target block only for one with an actual change,
    every unchanged (plugin, target) pair rolled into one summary line instead of repeating a
    `=== plugin ===`/"nothing to do" block for each (the measured complaint: 33 lines of that on a
    handful of real targets). `--verbose` lists the unchanged ones individually.
    """
    unchanged: list[str] = []
    for plugin_name, by_target in result.items():
        if not by_target:
            print(
                style.paint(
                    f"\n=== {plugin_name} — not installed on this machine, skipped ===",
                    style.DIM,
                    color=color,
                )
            )
            continue
        for target, report in by_target.items():
            if report.has_changes:
                print(f"\n=== {style.paint(plugin_name, style.BOLD, color=color)} ===")
                print_rules_report(report, target, color=color)
            else:
                unchanged.append(f"{plugin_name} @ {target}")
    if not unchanged:
        return
    noun = "target" if len(unchanged) == 1 else "targets"
    tick = style.paint("✓", style.GREEN, color=color)
    summary = style.paint(f"{len(unchanged)} {noun} up to date", style.DIM, color=color)
    print(f"\n{tick} {summary}")
    if verbose:
        for line in unchanged:
            print(f"    {line}")
