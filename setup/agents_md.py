"""setup/agents_md.py — render AGENTS.md (+ CLAUDE.md symlink) at the workspace level.

Witness for the marker-wrapped idiom — groupe/repo levels replicate this once proven, not built
here. Every workspace-level section is generator-owned today (Workflow/Commands dropped —
duplicated `chantier`/`pinky --help`; Branch strategy dropped at repo level for the same reason
`branch_workflow` already resolves via `resolve_policy.py`) — so unlike
`inject_readme_sections_local`, this doesn't need `allow_first_run` guessing: everything from the
first `##` heading onward is generator-owned and replaced wholesale. Only the title line and the
free-text paragraph before the first heading are preserved verbatim.

Gotchas stays, unlike Workflow/Commands — nothing else proactively surfaces a workspace-wide trap
(no hook, no skill), same reasoning that kept the accumulation note in Cross-Package Patterns.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from . import state_file
from .common import WORKSPACE_ROOT

MARK = {
    "packages": (
        "<!-- pinky:agents-packages:start -->",
        "<!-- pinky:agents-packages:end -->",
    ),
    "cross_package_patterns": (
        "<!-- pinky:agents-cross-package-patterns:start -->",
        "<!-- pinky:agents-cross-package-patterns:end -->",
    ),
    "gotchas": (
        "<!-- pinky:agents-gotchas:start -->",
        "<!-- pinky:agents-gotchas:end -->",
    ),
    "behavior": (
        "<!-- pinky:agents-behavior:start -->",
        "<!-- pinky:agents-behavior:end -->",
    ),
}

ACCUMULATION_NOTE = (
    "AGENTS.md accumulates: root → repo, each level states only its own layer."
)

GOTCHAS = [
    (
        "Injected IDE context (open file, selection) is noise — never act on it unless "
        "explicitly referenced."
    ),
    (
        "A raw `claude plugin install` places a plugin but skips its `rules` distribution and "
        "the reconciliation ledger — use `pinky plugins reconcile [--apply]` then `pinky rules` "
        "instead."
    ),
]


def _pyproject_description(repo: Path) -> str:
    """`[project].description` from `repo/pyproject.toml`, or "" if absent/unparseable."""
    path = repo / "pyproject.toml"
    if not path.is_file():
        return ""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return ""
    return data.get("project", {}).get("description", "")


def _discover_repos_under(workspace_root: Path) -> list[Path]:
    """Every git repo under `workspace_root`, up to one directory deep — same walk as
    `precommit.discover_repos()`, parameterized instead of reading the global `WORKSPACE_ROOT`
    (this module always has an explicit root to hand: the workspace being rendered, real or a
    test fixture — no reason to go through global state for it).
    """
    seen: dict[str, Path] = {}
    for path in sorted(workspace_root.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / ".git").exists():
            seen[path.name] = path
            continue
        for nested in sorted(path.iterdir()):
            if nested.is_dir() and (nested / ".git").exists():
                seen[nested.name] = nested
    return list(seen.values())


def packages_table(workspace_root: Path) -> str:
    """One row per top-level directory that contains a repo (itself, or nested one level deep),
    grouped by its top-level ancestor. A directory with no `.git` anywhere under it (docs, kanban,
    backups — every `_`-prefixed dir here today) contributes no repo and is naturally absent, no
    separate exclusion list needed.
    """
    by_top: dict[str, list[Path]] = {}
    for repo in _discover_repos_under(workspace_root):
        top = repo.relative_to(workspace_root).parts[0]
        by_top.setdefault(top, []).append(repo)

    rows = ["| Package | Description | Path |", "|---|---|---|"]
    for top in sorted(by_top):
        repos = by_top[top]
        if len(repos) == 1 and repos[0].name == top:
            desc = _pyproject_description(repos[0]) or "—"
        else:
            desc = ", ".join(sorted(r.name for r in repos))
        rows.append(f"| {top} | {desc} | `{top}/` |")
    return "\n".join(rows)


def discover_groups(workspace_root: Path) -> list[Path]:
    """Every top-level directory that is a *group* — holds one or more repos nested one level
    down — as opposed to a standalone repo directly at depth 1. Same split `packages_table` already
    computes for its own rows, exposed here so a caller can render one group's AGENTS.md without
    rendering every group in the workspace.
    """
    by_top: dict[str, list[Path]] = {}
    for repo in _discover_repos_under(workspace_root):
        top = repo.relative_to(workspace_root).parts[0]
        by_top.setdefault(top, []).append(repo)
    return [
        workspace_root / top
        for top, repos in sorted(by_top.items())
        if not (len(repos) == 1 and repos[0].name == top)
    ]


def gotchas_section() -> str:
    """Fixed workspace-wide traps — same treatment as `ACCUMULATION_NOTE`/`behavior_section`:
    nothing computes these from a file, and nothing else proactively surfaces them (unlike
    Commands, which duplicated `pinky --help` and was dropped)."""
    return "\n".join(f"- {text}" for text in GOTCHAS)


def behavior_section(workspace_root: Path) -> str:
    """Render `settings.pinky.json["behavior"]`, in file order — empty (not absent) if the key is
    missing, so a fresh workspace gets a visibly-empty section instead of a silent skip."""
    settings_path = workspace_root / ".claude" / "settings.pinky.json"
    if not settings_path.is_file():
        return ""
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    behavior = data.get("behavior", {})
    return "\n".join(f"- {text}" for text in behavior.values())


def _wrapped(key: str, body: str) -> str:
    start, end = MARK[key]
    return f"{start}\n\n{body}\n\n{end}"


def render_workspace_agents_md(workspace_root: Path, existing: str | None) -> str:
    """Build the full AGENTS.md content. `existing`: the current file's content if any — only its
    title line and free-text intro (before the first `##`) survive; everything from there on is
    generator-owned and rebuilt.
    """
    name = workspace_root.name
    intro = f"# AGENTS.md — {name}\n"
    if existing:
        m = re.match(r"(.*?)(?=\n## )", existing, re.S)
        if m:
            intro = m.group(1).rstrip("\n") + "\n"

    sections = [
        intro.rstrip("\n"),
        "## Packages\n\n" + _wrapped("packages", packages_table(workspace_root)),
        "## Cross-Package Patterns\n\n"
        + _wrapped("cross_package_patterns", ACCUMULATION_NOTE),
        "## Gotchas\n\n" + _wrapped("gotchas", gotchas_section()),
        "## Behavior policy\n\n"
        + _wrapped("behavior", behavior_section(workspace_root)),
    ]
    return "\n\n".join(sections) + "\n"


def _symlink_claude_md(root: Path) -> None:
    """`CLAUDE.md` → `AGENTS.md`, same directory — merge-safe, never touches an
    existing non-symlink `CLAUDE.md` a human may have hand-created outside this generator's
    reach (would only happen by manual `cp` instead of `ln -s`, but never silently clobbered)."""
    claude_path = root / "CLAUDE.md"
    if claude_path.is_symlink() or claude_path.is_file():
        claude_path.unlink()
    claude_path.symlink_to("AGENTS.md")


def write_workspace_agents_md(workspace_root: Path = WORKSPACE_ROOT) -> Path:
    """Render and write `<workspace_root>/AGENTS.md`, symlink `CLAUDE.md` to it."""
    agents_path = workspace_root / "AGENTS.md"
    existing = (
        agents_path.read_text(encoding="utf-8") if agents_path.is_file() else None
    )
    agents_path.write_text(
        render_workspace_agents_md(workspace_root, existing), encoding="utf-8"
    )
    _symlink_claude_md(workspace_root)
    return agents_path


def render_group_agents_md(
    group_root: Path, workspace_root: Path, existing: str | None
) -> str:
    """Same shape as the workspace render (Packages + Cross-Package Patterns), scoped to the
    repos nested directly under `group_root` only."""
    name = group_root.name
    intro = f"# AGENTS.md — {name}\n"
    if existing:
        m = re.match(r"(.*?)(?=\n## )", existing, re.S)
        if m:
            intro = m.group(1).rstrip("\n") + "\n"

    repos = [
        r
        for r in _discover_repos_under(workspace_root)
        if r.relative_to(workspace_root).parts[0] == name
    ]
    rows = ["| Package | Description | Path |", "|---|---|---|"]
    for r in sorted(repos, key=lambda p: p.name):
        rows.append(f"| {r.name} | {_pyproject_description(r) or '—'} | `{r.name}/` |")

    sections = [
        intro.rstrip("\n"),
        "## Packages\n\n" + _wrapped("packages", "\n".join(rows)),
        "## Cross-Package Patterns\n\n"
        + _wrapped("cross_package_patterns", ACCUMULATION_NOTE),
    ]
    return "\n\n".join(sections) + "\n"


def write_group_agents_md(
    group_root: Path, workspace_root: Path = WORKSPACE_ROOT
) -> Path:
    """Render and write `<group_root>/AGENTS.md`, symlink `CLAUDE.md` to it."""
    agents_path = group_root / "AGENTS.md"
    existing = (
        agents_path.read_text(encoding="utf-8") if agents_path.is_file() else None
    )
    agents_path.write_text(
        render_group_agents_md(group_root, workspace_root, existing), encoding="utf-8"
    )
    _symlink_claude_md(group_root)
    return agents_path


def _context_md_glossary(repo: Path) -> str:
    """The naming-glossary body of `<repo>/CONTEXT.md` — everything after its title/freshness-tag
    and the "Single source of truth for naming..." lead sentence, which AGENTS.md's own
    header/intro already covers, no need for a second copy. Empty if the repo has no CONTEXT.md.
    """
    path = repo / "CONTEXT.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    paragraphs = text.split("\n\n")
    return "\n\n".join(paragraphs[2:]).strip()


def _repo_default_body(repo: Path) -> str:
    """The hand-authored body (`## Naming glossary` + `## Repo conventions`) a fresh, never-seeded
    repo AGENTS.md gets — folds in `CONTEXT.md`'s glossary if present. Factored out of
    `write_repo_agents_md` so `render_standalone_agents_md` can seed the same default body for a
    repo that has no AGENTS.md yet, without writing a real file first.
    """
    glossary = _context_md_glossary(repo)
    return (
        "## Naming glossary\n\n"
        f"{glossary or '_Not written yet._'}\n\n"
        "## Repo conventions\n\n"
        "_Not written yet._"
    )


def write_repo_agents_md(repo: Path) -> Path | None:
    """Seed `<repo>/AGENTS.md` once, folding in `CONTEXT.md`'s naming glossary if present (then
    deleting it — one canonical file, not two). Never touches an AGENTS.md that already exists:
    Naming glossary/Repo conventions are hand-authored from here on, no generator-owned section at
    this level (unlike workspace/groupe) — returns None (nothing written) when already present.
    """
    agents_path = repo / "AGENTS.md"
    if agents_path.is_file():
        return None

    content = f"# AGENTS.md — {repo.name}\n\n{_repo_default_body(repo)}\n"
    agents_path.write_text(content, encoding="utf-8")
    _symlink_claude_md(repo)

    context_path = repo / "CONTEXT.md"
    if context_path.is_file():
        context_path.unlink()

    return agents_path


def render_standalone_agents_md(
    repo: Path, workspace_root: Path, existing: str | None
) -> str:
    """Full render for a repo about to leave the workspace (`--standalone`, a one-time extraction
    gesture — never generated by default). Fuses the workspace's fixed sections
    (Gotchas, Behavior policy — the ones a departing repo loses once there is no ancestor
    AGENTS.md left to accumulate from) with the repo's own hand-authored body (Naming glossary,
    Repo conventions), preserved verbatim. Packages/Cross-Package Patterns are dropped: both
    describe siblings a standalone repo no longer sees.

    Idempotent across repeated `--standalone` runs: detects a PRIOR standalone render (the
    Behavior-policy end marker already present) and re-extracts the body from AFTER it, so Gotchas/
    Behavior never get mistaken for hand-authored content and duplicated below the freshly
    regenerated copy.
    """
    name = repo.name
    intro = f"# AGENTS.md — {name}\n"
    body = _repo_default_body(repo)

    if existing:
        behavior_end = MARK["behavior"][1]
        if behavior_end in existing:
            body = existing.split(behavior_end, 1)[1].strip()
            m = re.match(r"(.*?)(?=\n## Gotchas)", existing, re.S)
        else:
            m = re.match(r"(.*?)(?=\n## )", existing, re.S)
            m2 = re.search(r"\n(## .*)", existing, re.S)
            if m2:
                body = m2.group(1).strip()
        if m:
            intro = m.group(1).rstrip("\n") + "\n"

    sections = [
        intro.rstrip("\n"),
        "## Gotchas\n\n" + _wrapped("gotchas", gotchas_section()),
        "## Behavior policy\n\n"
        + _wrapped("behavior", behavior_section(workspace_root)),
        body,
    ]
    return "\n\n".join(sections) + "\n"


def write_standalone_agents_md(
    repo: Path, workspace_root: Path = WORKSPACE_ROOT
) -> Path:
    """Render and write the repo's full standalone `AGENTS.md` (`--standalone`), symlink
    `CLAUDE.md`. Unlike `write_repo_agents_md`, this DOES overwrite an existing file —
    only its hand-authored body survives, never the generated prefix."""
    agents_path = repo / "AGENTS.md"
    existing = (
        agents_path.read_text(encoding="utf-8") if agents_path.is_file() else None
    )
    agents_path.write_text(
        render_standalone_agents_md(repo, workspace_root, existing), encoding="utf-8"
    )
    _symlink_claude_md(repo)
    return agents_path


def _record_posed(path: Path, workspace_root: Path) -> None:
    # clé stable par emplacement (pas par contenu) — un futur --check-drift compare `value` (le
    # hash posé) au hash courant, comme le fait déjà `state_file.status_of` pour les autres cibles.
    key = f"agents-md:{path.relative_to(workspace_root)}"
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    state_file.record_posed(key, path=str(path), value=value)


def write_standalone_agents_md_recorded(
    repo: Path, workspace_root: Path = WORKSPACE_ROOT
) -> Path:
    """`write_standalone_agents_md` + install-ledger record — the entry point a distribution run
    calls (`--agents-md --standalone`), mirroring what `generate_agents_md` does for the default
    fan-out."""
    path = write_standalone_agents_md(repo, workspace_root)
    _record_posed(path, workspace_root)
    return path


def generate_agents_md(
    repos: list[Path], workspace_root: Path = WORKSPACE_ROOT
) -> list[Path]:
    """Render/write every AGENTS.md a distribution run touches: the workspace (always — its
    Packages table reflects the whole workspace regardless of which repo was targeted), the group
    of each repo in `repos` (never a sibling group `repos` didn't touch), and each repo itself
    (write-once, see `write_repo_agents_md`). Records every path actually written in the install
    ledger (`state_file`). Returns the paths written, in that order.
    """
    written = [write_workspace_agents_md(workspace_root)]

    touched_groups = {
        r.relative_to(workspace_root).parts[0]
        for r in repos
        if len(r.relative_to(workspace_root).parts) > 1
    }
    for group in discover_groups(workspace_root):
        if group.name in touched_groups:
            written.append(write_group_agents_md(group, workspace_root))

    for repo in repos:
        path = write_repo_agents_md(repo)
        if path is not None:
            written.append(path)

    for path in written:
        _record_posed(path, workspace_root)
    return written
