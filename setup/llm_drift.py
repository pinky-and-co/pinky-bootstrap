"""LLM drift — what agents leave in Python sources that every later read pays for.

A drift kind pairs a detector with a fixer, the fixer only when the fix is mechanical and provably
keeps the program. ``scan`` reports the findings of the requested kinds and each repo's comment
weight; ``fix`` applies a kind's fixer, re-sorts imports and reformats with the ruff release prek
pins, then reports what the cleanup saves on every future read.

Token counts are estimates — characters over :data:`CHARS_PER_TOKEN`: the percentages hold, the
absolute numbers are approximate. ``narrative`` and ``long-comment`` are the distributed
``check_narrative_comments`` hook itself, imported rather than restated, so the pre-commit warning
and this report never disagree on what a drift is.
"""

from __future__ import annotations

import ast
import io
import json
import math
import re
import shutil
import subprocess
import tokenize
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .common import CORE_PRECOMMIT_DIR
from .precommit import discover_repos

import check_narrative_comments

CHARS_PER_TOKEN = 4
SCAN_KINDS_DEFAULT = ["narrative", "long-comment"]

_DIRECTIVE = re.compile(
    r"#\s*(?:noqa|type:|nosec|pragma|fmt:|pylint:|mypy:|isort:|ruff:|pyright:|pinky:|-\*-)"
)
_RUFF_REV = re.compile(r"ruff-pre-commit\s*\n\s*rev:\s*v?([\w.]+)")
_UNREADABLE = (
    OSError,
    SyntaxError,
    tokenize.TokenError,
    UnicodeDecodeError,
    ValueError,
)


@dataclass(frozen=True)
class Hit:
    """One drift occurrence in a file: the line it starts on and its text as written."""

    line: int
    text: str


@dataclass(frozen=True)
class DriftKind:
    """A named drift: how to find it in a file, and how to remove it when that is mechanical."""

    name: str
    detect: Callable[[Path], list[Hit]]
    fix: Callable[[str], str] | None = None


@dataclass(frozen=True)
class Weight:
    """What reading some sources costs: non-blank lines, full-line comments, characters."""

    lines: int = 0
    comment_lines: int = 0
    chars: int = 0

    @property
    def tokens(self) -> int:
        """Estimated tokens, characters over :data:`CHARS_PER_TOKEN` rounded up."""
        return math.ceil(self.chars / CHARS_PER_TOKEN)

    def __add__(self, other: Weight) -> Weight:
        """Sum two weights field by field."""
        return Weight(
            self.lines + other.lines,
            self.comment_lines + other.comment_lines,
            self.chars + other.chars,
        )


@dataclass(frozen=True, order=True)
class Finding:
    """A hit located in a repo: path relative to the repo root, line, drift kind, text."""

    path: Path
    line: int
    kind: str
    text: str


@dataclass
class RepoScan:
    """What ``scan`` found in one repo."""

    repo: Path
    files: int = 0
    weight: Weight = field(default_factory=Weight)
    findings: list[Finding] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


@dataclass
class RepoFix:
    """What ``fix`` changed in one repo, and what the changed files weighed before and after."""

    repo: Path
    total: Weight = field(default_factory=Weight)
    before: Weight = field(default_factory=Weight)
    after: Weight = field(default_factory=Weight)
    changed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)


def _comment_tokens(source: str) -> list[tokenize.TokenInfo]:
    """The deletable comments of a source: all but the shebang, tool directives and PEP 723."""
    comments = []
    in_pep723 = False
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT:
            continue
        text = tok.string.strip()
        if text == "# /// script":
            in_pep723 = True
        if (
            in_pep723
            or (tok.start[0] == 1 and text.startswith("#!"))
            or _DIRECTIVE.search(text)
        ):
            in_pep723 = in_pep723 and text != "# ///"
            continue
        comments.append(tok)
    return comments


def strip_comments(source: str) -> str:
    """The source without its deletable comments.

    A full-line comment loses its line, along with a blank line it would leave orphaned; a trailing
    comment is cut from its ``#``. A ``#`` inside a string or a docstring is never a comment here.

    Args:
        source: Python source text.

    Returns:
        The same program without its comments.

    Raises:
        ValueError: The stripped source would not be the same program.
    """
    drop: set[int] = set()
    cut: dict[int, int] = {}
    for tok in _comment_tokens(source):
        if tok.line.lstrip().startswith("#"):
            drop.add(tok.start[0])
        else:
            cut[tok.start[0]] = tok.start[1]
    lines = source.splitlines(keepends=True)
    for number, col in cut.items():
        raw = lines[number - 1]
        lines[number - 1] = raw[:col].rstrip() + ("\n" if raw.endswith("\n") else "")
    kept: list[str] = []
    after_drop = False
    for number, raw in enumerate(lines, 1):
        if number in drop:
            after_drop = True
            continue
        if after_drop and not raw.strip() and (not kept or not kept[-1].strip()):
            after_drop = False
            continue
        after_drop = False
        kept.append(raw)
    stripped = "".join(kept)
    if ast.dump(ast.parse(source)) != ast.dump(ast.parse(stripped)):
        raise ValueError("stripping comments changed the program")
    return stripped


def weigh(source: str) -> Weight:
    """What reading one source costs.

    Args:
        source: Python source text.

    Returns:
        Its non-blank lines, full-line comments and characters.
    """
    lines = [line for line in source.splitlines() if line.strip()]
    comments = sum(1 for line in lines if line.lstrip().startswith("#"))
    return Weight(len(lines), comments, len(source))


def _comment_hits(path: Path) -> list[Hit]:
    """Every deletable comment of a file."""
    source = path.read_text(encoding="utf-8")
    return [Hit(tok.start[0], tok.string.strip()) for tok in _comment_tokens(source)]


def _hook_hits(path: Path, *, long_blocks: bool) -> list[Hit]:
    """The narrative hook's findings of one family: history, or over-long comment blocks."""
    hits = []
    for finding in check_narrative_comments.check_file(path):
        kinds = finding.kinds.split(", ")
        is_long = any(kind.startswith("long comment") for kind in kinds)
        has_history = any(not kind.startswith("long comment") for kind in kinds)
        if is_long if long_blocks else has_history:
            hits.append(Hit(finding.line, finding.text))
    return hits


def _narrative_hits(path: Path) -> list[Hit]:
    """Dates, requirement ids, chantier, card and file references in comments and docstrings."""
    return _hook_hits(path, long_blocks=False)


def _long_comment_hits(path: Path) -> list[Hit]:
    """Full-line comment blocks longer than the hook's limit, one hit per block."""
    return _hook_hits(path, long_blocks=True)


DRIFT_KINDS: list[DriftKind] = [
    DriftKind("comments", _comment_hits, strip_comments),
    DriftKind("narrative", _narrative_hits),
    DriftKind("long-comment", _long_comment_hits),
]


def drift_kind(name: str) -> DriftKind:
    """The registered drift kind of that name.

    Args:
        name: A drift kind name.

    Returns:
        Its registry entry.

    Raises:
        KeyError: No kind of that name is registered.
    """
    for kind in DRIFT_KINDS:
        if kind.name == name:
            return kind
    known = ", ".join(kind.name for kind in DRIFT_KINDS)
    raise KeyError(f"unknown drift kind {name!r} — known: {known}")


def python_files(repo: Path) -> list[Path]:
    """The repo's tracked Python files, minus ``scripts/hooks/``: those copies are cleaned at their source.

    Args:
        repo: A git repository root.

    Returns:
        Absolute paths, in git's order.
    """
    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [
        repo / name
        for name in listed.split("\0")
        if name and not name.startswith("scripts/hooks/")
    ]


def scan_repo(repo: Path, kinds: list[str]) -> RepoScan:
    """Findings of the given drift kinds, and the comment weight, of one repo.

    Args:
        repo: A git repository root.
        kinds: Drift kind names to report.

    Returns:
        The scan; a file that cannot be read or parsed is listed as skipped.
    """
    scan = RepoScan(repo)
    selected = [drift_kind(name) for name in kinds]
    for path in python_files(repo):
        rel = path.relative_to(repo)
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source)
            hits = [(kind.name, hit) for kind in selected for hit in kind.detect(path)]
        except _UNREADABLE:
            scan.skipped.append(rel)
            continue
        scan.files += 1
        scan.weight += weigh(source)
        scan.findings += [Finding(rel, hit.line, name, hit.text) for name, hit in hits]
    scan.findings.sort()
    return scan


def ruff_version() -> str:
    """The ruff release prek runs, read from the python extra so a fix never disagrees with it.

    Returns:
        The version, without its ``v`` prefix.

    Raises:
        RuntimeError: The python extra pins no ruff-pre-commit revision.
    """
    text = (CORE_PRECOMMIT_DIR / "extras" / "python.yaml").read_text(encoding="utf-8")
    match = _RUFF_REV.search(text)
    if match is None:
        raise RuntimeError("extras/python.yaml pins no ruff-pre-commit rev")
    return match.group(1)


def _reformat(repo: Path, files: list[Path]) -> None:
    """Re-sort imports and reformat files with prek's ruff, as their next commit would require."""
    uvx = shutil.which("uvx")
    if uvx is None:
        print(f"  ⚠️ uvx not found — run ruff format yourself in {repo.name}")
        return
    ruff = f"ruff@{ruff_version()}"
    names = [str(path) for path in files]
    for args in (
        ["check", "--fix", "--select", "I001", "--quiet"],
        ["format", "--quiet"],
    ):
        subprocess.run(
            [uvx, ruff, *args, *names], cwd=repo, capture_output=True, check=False
        )


def fix_repo(
    repo: Path, kind_name: str, *, dry_run: bool, reformat: bool = True
) -> RepoFix:
    """Apply one drift kind's fixer to every Python file of a repo.

    Args:
        repo: A git repository root.
        kind_name: A drift kind that has a fixer.
        dry_run: Compute the savings without writing anything.
        reformat: After writing, re-sort imports and reformat the changed files with prek's ruff.

    Returns:
        What changed and what it saves; a file that cannot be parsed, or whose program would
        change, is listed as skipped and left untouched.

    Raises:
        ValueError: The kind has no fixer.
    """
    kind = drift_kind(kind_name)
    if kind.fix is None:
        fixable = ", ".join(k.name for k in DRIFT_KINDS if k.fix)
        raise ValueError(f"drift kind {kind_name!r} has no fixer — fixable: {fixable}")
    result = RepoFix(repo)
    rewritten: dict[Path, str] = {}
    for path in python_files(repo):
        rel = path.relative_to(repo)
        try:
            source = path.read_text(encoding="utf-8")
            fixed = kind.fix(source)
        except _UNREADABLE:
            result.skipped.append(rel)
            continue
        result.total += weigh(source)
        if fixed != source:
            result.changed.append(rel)
            result.before += weigh(source)
            rewritten[path] = fixed
    if dry_run:
        for fixed in rewritten.values():
            result.after += weigh(fixed)
        return result
    for path, fixed in rewritten.items():
        path.write_text(fixed, encoding="utf-8")
    if reformat and rewritten:
        _reformat(repo, list(rewritten))
    for path in rewritten:
        result.after += weigh(path.read_text(encoding="utf-8"))
    return result


def _k(tokens: int) -> str:
    """Compact token count: 950, 1.2k."""
    return f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)


def format_scan(scan: RepoScan) -> list[str]:
    """Human report of one repo's scan: header, one line per finding, per-kind counts.

    Args:
        scan: A repo scan.

    Returns:
        The report lines.
    """
    weight = scan.weight
    share = 100 * weight.comment_lines / weight.lines if weight.lines else 0.0
    lines = [
        f"== {scan.repo.name} · {scan.files} .py · {share:.1f} % comment lines · "
        f"≈{_k(weight.tokens)} tokens"
    ]
    lines += [f"  {f.path}:{f.line}  {f.kind}  {f.text}" for f in scan.findings]
    lines += [f"  skipped (does not parse): {path}" for path in scan.skipped]
    counts = Counter(f.kind for f in scan.findings)
    summary = " · ".join(
        f"{kind.name} {counts[kind.name]}" for kind in DRIFT_KINDS if counts[kind.name]
    )
    lines.append(f"  {summary or 'no drift'}")
    return lines


def format_fix(fix: RepoFix, *, dry_run: bool) -> str:
    """One-line human report of a repo fix: files changed, lines removed, tokens saved per read.

    Args:
        fix: A repo fix.
        dry_run: Whether the fix was computed without writing.

    Returns:
        The report line.
    """
    if not fix.changed:
        return f"{fix.repo.name} · nothing to fix"
    saved = fix.before.tokens - fix.after.tokens
    share = 100 * saved / fix.total.tokens if fix.total.tokens else 0.0
    count = len(fix.changed)
    line = (
        f"{fix.repo.name} · {count} file{'' if count == 1 else 's'} · "
        f"−{fix.before.lines - fix.after.lines} lines · "
        f"≈−{_k(saved)} tokens per read (−{share:.1f} % of the repo)"
    )
    return line + (" · dry-run, nothing written" if dry_run else "")


def scans_to_json(scans: list[RepoScan]) -> str:
    """Machine-readable scans — the snapshot a before/after comparison reads.

    Args:
        scans: Repo scans.

    Returns:
        A JSON array, one object per repo.
    """
    return json.dumps(
        [
            {
                "repo": scan.repo.name,
                "files": scan.files,
                "lines": scan.weight.lines,
                "comment_lines": scan.weight.comment_lines,
                "chars": scan.weight.chars,
                "tokens": scan.weight.tokens,
                "findings": [
                    {
                        "path": str(f.path),
                        "line": f.line,
                        "kind": f.kind,
                        "text": f.text,
                    }
                    for f in scan.findings
                ],
                "skipped": [str(path) for path in scan.skipped],
            }
            for scan in scans
        ],
        ensure_ascii=False,
        indent=2,
    )


def select_repos(name: str | None, every: bool) -> list[Path]:
    """The repos a run covers: one by name, all of the workspace, or the one holding the cwd.

    Args:
        name: A repo name to pick among the workspace's repos.
        every: Cover every repo of the workspace.

    Returns:
        Repo roots; empty when the name matches nothing or the cwd is in no repo.
    """
    if every:
        return discover_repos()
    if name:
        return [repo for repo in discover_repos() if repo.name == name]
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [Path(top.stdout.strip())] if top.returncode == 0 else []


def run(
    action: str, repos: list[Path], kinds: list[str], *, dry_run: bool, as_json: bool
) -> int:
    """Run ``scan`` or ``fix`` over repos and print the report.

    Args:
        action: ``scan`` or ``fix``.
        repos: Repo roots.
        kinds: Drift kind names; empty means the action's default.
        dry_run: With ``fix``, compute the savings without writing.
        as_json: With ``scan``, print JSON instead of the human report.

    Returns:
        1 when no repo was selected, a kind is unknown or unfixable, or a file was skipped;
        0 otherwise.
    """
    if not repos:
        print("llm-drift: no repo — pass --repo NAME or --all, or run it inside a repo")
        return 1
    try:
        if action == "scan":
            scans = [scan_repo(repo, kinds or SCAN_KINDS_DEFAULT) for repo in repos]
            report = (
                scans_to_json(scans)
                if as_json
                else "\n".join(line for scan in scans for line in format_scan(scan))
            )
            print(report)
            return 1 if any(scan.skipped for scan in scans) else 0
        fixes = [
            fix_repo(repo, name, dry_run=dry_run)
            for repo in repos
            for name in (kinds or ["comments"])
        ]
    except (KeyError, ValueError) as exc:
        print(f"llm-drift: {exc.args[0]}")
        return 1
    for fix in fixes:
        print(format_fix(fix, dry_run=dry_run))
        for path in fix.skipped:
            print(f"  skipped (does not parse, or its program would change): {path}")
    return 1 if any(fix.skipped for fix in fixes) else 0
