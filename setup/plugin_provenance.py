"""setup/plugin_provenance.py — who installed what.

`installed_plugins.json` dates every install (`installedAt`) but never says who ran it: `pinky`, an
agent session calling `claude plugin install` directly, or a hook (`pc-autodiscovery`, `chantier`,
`spawn-workers`). Claude Code keeps each session's transcript under `~/.claude/projects/`, and an
agent's `claude plugin install …` is a Bash tool call there, with the session id, the directory
and a timestamp. Matching a registry entry to the closest such command is the proof; an entry no
command matches was written by a hook or a script, which never go through the Bash tool.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_REGISTRY = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
_PROJECTS = Path.home() / ".claude" / "projects"
_WINDOW_SECONDS = 120
_INSTALL_COMMAND = re.compile(
    r"claude plugin (?:install|enable)|pinky (?:install|claude-plugin)"
)
_MAX_COMMAND_CHARS = 160


@dataclass(frozen=True)
class Origin:
    """The Bash tool call that ran an install: the session, where, what, when."""

    session_id: str
    cwd: str
    command: str
    timestamp: str


@dataclass(frozen=True)
class EntryOrigin:
    """One registry entry and the command that created it (`None`: no command matches)."""

    plugin_id: str
    scope: str
    project_path: str | None
    installed_at: str
    origin: Origin | None


def _seconds(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()


def _install_commands(projects_dir: Path) -> list[Origin]:
    """Every install-looking Bash command in every session transcript, read in a single pass."""
    found: list[Origin] = []
    for transcript in sorted(projects_dir.glob("*/*.jsonl")):
        with transcript.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                # filtre bon marché avant de parser le JSON : la plupart des lignes n'y touchent pas
                if "plugin" not in line and "pinky" not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = event.get("message", {}).get("content")
                if not isinstance(content, list):
                    continue
                for item in content:
                    if item.get("type") != "tool_use" or item.get("name") != "Bash":
                        continue
                    command = item.get("input", {}).get("command", "")
                    if _INSTALL_COMMAND.search(command) and event.get("timestamp"):
                        found.append(
                            Origin(
                                session_id=event.get("sessionId", ""),
                                cwd=event.get("cwd", ""),
                                command=command,
                                timestamp=event["timestamp"],
                            )
                        )
    return found


def _closest(
    plugin_id: str, installed_at: str, commands: list[Origin]
) -> Origin | None:
    bare_name = plugin_id.split("@", 1)[0]
    at = _seconds(installed_at)
    near = [
        (abs(_seconds(c.timestamp) - at), c) for c in commands if bare_name in c.command
    ]
    near = [(gap, c) for gap, c in near if gap <= _WINDOW_SECONDS]
    return min(near, key=lambda pair: pair[0])[1] if near else None


def registry_origins(
    registry_path: Path = _REGISTRY, projects_dir: Path = _PROJECTS
) -> list[EntryOrigin]:
    """One `EntryOrigin` per registry entry, matched to the closest install command within
    `_WINDOW_SECONDS` of its `installedAt`."""
    plugins = json.loads(registry_path.read_text(encoding="utf-8")).get("plugins", {})
    commands = _install_commands(projects_dir)
    return [
        EntryOrigin(
            plugin_id=plugin_id,
            scope=entry.get("scope", "?"),
            project_path=entry.get("projectPath"),
            installed_at=entry["installedAt"],
            origin=_closest(plugin_id, entry["installedAt"], commands),
        )
        for plugin_id, entries in plugins.items()
        for entry in entries
        if entry.get("installedAt")
    ]


def format_origins(entries: list[EntryOrigin]) -> str:
    """The report: one header per entry, then the session that ran it or the absence of one."""
    lines: list[str] = []
    for entry in entries:
        where = f" {entry.project_path}" if entry.project_path else ""
        when = _stamp(entry.installed_at)
        lines.append(f"{entry.plugin_id}  {entry.scope}{where}  {when}")
        if entry.origin is None:
            lines.append(
                "    no matching command in the transcripts: a hook or a script"
            )
            continue
        origin = entry.origin
        lines.append(
            f"    session {origin.session_id[:8]} in {origin.cwd}: "
            f"{origin.command[:_MAX_COMMAND_CHARS]}"
        )
    return "\n".join(lines)


def _stamp(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).strftime(
        "%Y-%m-%d %H:%M"
    )
