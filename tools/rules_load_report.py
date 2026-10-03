"""
rules_load_report.py — Measure the workspace-rule bytes each Claude Code actor has in context.

Reads the JSONL transcripts under ``~/.claude/projects/<project>/``: the main session
(``<session>.jsonl``) and each subagent (``<session>/subagents/agent-<id>.jsonl``, typed by
its sibling ``agent-<id>.meta.json``). A rule file is a path under a ``.claude/rules/`` or
``.claude/rules-content/`` directory; CLAUDE.md / AGENTS.md are not rules.

Three loads are told apart, each counted once per path per transcript:

- ``session-start``: ``instructions`` attachment (rule bodies and lazy stubs), rules/ path.
- ``lazy-stub-or-path``: ``nested_memory`` attachment (path-triggered), rules/ path.
- ``content-read``: a ``Read`` of a ``rules-content/`` file, bytes of the text returned.

Sessions are bucketed by the first timestamp of the main transcript into a "before" and an
"after" window around a cutover; subagents follow their parent session. Without ``--since``
the "before" window spans every recorded session of the matching projects.

Usage:

    uv run python tools/rules_load_report.py

    uv run python tools/rules_load_report.py --project pinky --before 2026-10-01T00:00 \\
        --after 2026-10-03T21:00 --since 2026-09-15T00:00

Naive ISO bounds are local time; a trailing ``Z`` or offset is honoured.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MAIN = "main"
REVIEWER = "pc-core:reviewer"
SESSION_START = "session-start"
LAZY = "lazy-stub-or-path"
READ = "content-read"
KINDS = (SESSION_START, LAZY, READ)
RULES_DIRS = ("/.claude/rules/", "/.claude/rules-content/")
CONTENT_DIR = "/.claude/rules-content/"
DEFAULT_BEFORE = "2026-10-01T00:00"
DEFAULT_AFTER = "2026-10-03T21:00"
NO_SESSION = "no session"

Loads = dict[str, tuple[str, int]]


@dataclass
class Windows:
    """Per-window, per-actor load maps: {actor_name: [load_maps]}."""

    data: dict

    @staticmethod
    def create(before: dict, after: dict) -> Windows:  # type: ignore
        """Create a Windows instance from before/after dicts."""
        return Windows({"before": before, "after": after})

    def as_dict(self) -> dict:
        """Return the dict representation for iteration."""
        return self.data


@dataclass
class CollectResult:
    """Result of a collect() operation."""

    windows: Windows
    ignored: int


def parse_bound(text: str) -> datetime:
    """Parse an ISO timestamp into an aware UTC datetime (naive input is local time)."""
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def is_rule_path(path: str) -> bool:
    """Tell whether a file path lies under a ``.claude/rules`` or ``rules-content`` dir."""
    return any(marker in path for marker in RULES_DIRS)


def _entries(path: Path) -> Iterator[dict]:
    """Yield the JSON objects of a transcript, skipping unreadable lines."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def _size(text: object) -> int:
    """UTF-8 byte length of a string, 0 for anything else."""
    return len(text.encode("utf-8")) if isinstance(text, str) else 0


def _result_text(entry: dict, block: dict) -> str:
    """Text returned by a Read: the raw file content, else the tool_result body."""
    result = entry.get("toolUseResult")
    if isinstance(result, dict) and isinstance(result.get("file"), dict):
        content = result["file"].get("content")
        if isinstance(content, str):
            return content
    body = block.get("content")
    if isinstance(body, list):
        return "".join(part.get("text", "") for part in body if isinstance(part, dict))
    return body if isinstance(body, str) else ""


def scan_transcript(path: Path) -> Loads:
    """Return ``{rule path: (kind, bytes)}``, the first load of each path winning."""
    loads: Loads = {}
    pending: dict[str, str] = {}

    def add(rule: str, kind: str, size: int) -> None:
        if is_rule_path(rule) and rule not in loads:
            loads[rule] = (kind, size)

    for entry in _entries(path):
        attachment = entry.get("attachment")
        if entry.get("type") == "attachment" and isinstance(attachment, dict):
            if attachment.get("type") == "instructions":
                for file in attachment.get("files") or []:
                    add(file.get("path", ""), SESSION_START, _size(file.get("content")))
            elif attachment.get("type") == "nested_memory":
                content = attachment.get("content")
                if isinstance(content, dict):
                    content = content.get("content")
                add(attachment.get("path", ""), LAZY, _size(content))
        message = entry.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            target = (block.get("input") or {}).get("file_path", "")
            if (
                block.get("type") == "tool_use"
                and block.get("name") == "Read"
                and CONTENT_DIR in target
            ):
                pending[block.get("id", "")] = target
            elif (
                block.get("type") == "tool_result"
                and block.get("tool_use_id") in pending
                and not block.get("is_error")
            ):
                text = _result_text(entry, block)
                add(pending[block["tool_use_id"]], READ, _size(text))
    return loads


def first_timestamp(path: Path) -> datetime | None:
    """Return the first parseable timestamp of a transcript, in UTC."""
    for entry in _entries(path):
        stamp = entry.get("timestamp")
        if isinstance(stamp, str):
            try:
                return parse_bound(stamp)
            except ValueError:
                continue
    return None


def subagent_transcripts(session_dir: Path) -> list[tuple[str, Path]]:
    """List ``(agentType, transcript)`` for a session's subagents (``unknown`` if no meta)."""
    found: list[tuple[str, Path]] = []
    for transcript in sorted((session_dir / "subagents").glob("agent-*.jsonl")):
        meta = transcript.with_suffix(".meta.json")
        agent_type = "unknown"
        try:
            agent_type = json.loads(meta.read_text(encoding="utf-8")).get(
                "agentType", "unknown"
            )
        except (OSError, ValueError, AttributeError):
            pass
        found.append((agent_type, transcript))
    return found


def collect(
    projects_dir: Path,
    project: str,
    before: datetime,
    after: datetime,
    since: datetime | None = None,
) -> CollectResult:
    """Gather per-window, per-actor load maps; also return the number of ignored sessions."""
    before_actors: dict[str, list[Loads]] = {}
    after_actors: dict[str, list[Loads]] = {}
    ignored = 0
    for proj in sorted(projects_dir.glob("*")):
        if not proj.is_dir() or project not in proj.name:
            continue
        for main in sorted(proj.glob("*.jsonl")):
            start = first_timestamp(main)
            if start is None:
                continue
            if since is not None and start < since:
                ignored += 1
                continue
            if start < before:
                actors = before_actors
            elif start >= after:
                actors = after_actors
            else:
                ignored += 1
                continue
            actors.setdefault(MAIN, []).append(scan_transcript(main))
            for agent_type, transcript in subagent_transcripts(main.with_suffix("")):
                actors.setdefault(agent_type, []).append(scan_transcript(transcript))
    windows = Windows.create(before=before_actors, after=after_actors)
    return CollectResult(windows=windows, ignored=ignored)


def _avg(loads: list[Loads], kind: str | None) -> float:
    """Average bytes per transcript for one kind (all kinds when None)."""
    total = sum(size for one in loads for k, size in one.values() if kind in (None, k))
    return total / len(loads)


def _table(rows: list[list[str]]) -> list[str]:
    """Align a header + rows: first column left, others right, two-space gutter."""
    widths = [
        max(len(row[i]) for row in rows if len(row) > i) for i in range(len(rows[0]))
    ]
    lines = []
    for row in rows:
        if len(row) == 2 and row[1] == NO_SESSION:
            lines.append(f"{row[0].ljust(widths[0])}  {NO_SESSION}")
            continue
        cells = [row[0].ljust(widths[0])] + [
            cell.rjust(widths[i]) for i, cell in enumerate(row) if i
        ]
        lines.append("  ".join(cells))
    return lines


def render(windows: Windows, ignored: int) -> str:
    """Render the full plain-text report."""
    windows_dict = windows.as_dict()
    names = {a for actors in windows_dict.values() for a in actors} | {MAIN}
    order = [MAIN] + sorted(names - {MAIN}, key=str.lower)
    out: list[str] = []
    for label in ("before", "after"):
        rows = [
            [
                "actor",
                "transcripts",
                "avg rule bytes/transcript",
                "avg session-start",
                "avg lazy-path",
                "avg content-read",
            ]
        ]
        for actor in order:
            loads = windows_dict[label].get(actor)
            if not loads:
                rows.append([actor, NO_SESSION])
                continue
            rows.append(
                [actor, str(len(loads))]
                + [f"{_avg(loads, k):.0f}" for k in (None, *KINDS)]
            )
        out += [label, *_table(rows), ""]
    out += [
        "session-start = injected at session start (rule bodies and lazy stubs)",
        "",
    ]

    rows = [["actor", "before", "after", "delta bytes", "delta %"]]
    for actor in order:
        pair = [windows_dict[w].get(actor) for w in ("before", "after")]
        if not all(pair):
            rows.append(
                [
                    actor,
                    *(NO_SESSION if not p else f"{_avg(p, None):.0f}" for p in pair),
                    "n/a",
                    "n/a",
                ]
            )
            continue
        old, new = (_avg(p, None) for p in pair if p)
        pct = f"{(new - old) / old * 100:+.1f}%" if old else "n/a"
        rows.append([actor, f"{old:.0f}", f"{new:.0f}", f"{new - old:+.0f}", pct])
    out += ["delta (after − before)", *_table(rows), ""]

    out.append("rules loaded in after window")
    for actor in order:
        loads = windows_dict["after"].get(actor)
        out.append(actor)
        if not loads:
            out.append(f"  {NO_SESSION}")
            continue
        counts = Counter(name for one in loads for name in {Path(p).name for p in one})
        if not counts:
            out.append("  none")
        out += [f"  {name}  {n}" for name, n in sorted(counts.items())]
    out.append("")

    def avg_text(window: str) -> str:
        loads = windows_dict[window].get(REVIEWER)
        return f"{_avg(loads, None):.0f}" if loads else NO_SESSION

    if any(REVIEWER in windows_dict[w] for w in windows_dict):
        out.append(
            f"summary: {REVIEWER} avg rule bytes before={avg_text('before')} "
            f"after={avg_text('after')}"
        )
    else:
        out.append(f"summary: no {REVIEWER} actor")
    if ignored:
        out.append(f"note: {ignored} session(s) ignored (between bounds)")
    return "\n".join(out) + "\n"


def _bound(text: str) -> datetime:
    """Argparse type wrapper for ``parse_bound``."""
    try:
        return parse_bound(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ISO timestamp: {text!r}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: print the report for the selected projects."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--projects-dir", type=Path, default=Path.home() / ".claude" / "projects"
    )
    parser.add_argument("--project", default="pinky", help="project-dir name substring")
    parser.add_argument("--before", type=_bound, default=_bound(DEFAULT_BEFORE))
    parser.add_argument("--after", type=_bound, default=_bound(DEFAULT_AFTER))
    parser.add_argument(
        "--since",
        type=_bound,
        default=None,
        help="lower bound of the 'before' window (ISO, naive = local time); without it "
        "'before' spans every recorded session of the matching projects",
    )
    args = parser.parse_args(argv)
    result = collect(
        args.projects_dir, args.project, args.before, args.after, args.since
    )
    sys.stdout.write(render(result.windows, result.ignored))
    return 0


if __name__ == "__main__":
    sys.exit(main())
