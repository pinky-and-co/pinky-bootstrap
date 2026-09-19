"""Who installed what: match a registry entry to the session transcript that ran the command."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_provenance


def _transcript(projects: Path, session: str, cwd: str, events: list[tuple[str, str]]):
    """One session file: `(timestamp, bash command)` per assistant tool call."""
    folder = projects / "-workspace-repo"
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for timestamp, command in events:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "sessionId": session,
                    "cwd": cwd,
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "input": {"command": command},
                            }
                        ]
                    },
                }
            )
        )
    (folder / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _registry(path: Path, key: str, scope: str, project_path: str | None, at: str):
    entry = {"scope": scope, "installedAt": at, "lastUpdated": at}
    if project_path:
        entry["projectPath"] = project_path
    path.write_text(json.dumps({"plugins": {key: [entry]}}), encoding="utf-8")


@pytest.fixture
def paths(tmp_path):
    return SimpleNamespace(
        projects=tmp_path / "projects", registry=tmp_path / "reg.json"
    )


def test_the_session_that_ran_the_install_command_is_found(paths):
    _transcript(
        paths.projects,
        "64197f4f",
        "/ws/pinky-agentic-plugins",
        [
            (
                "2026-09-17T23:52:02.432Z",
                "claude plugin install pc-delegate@mp --scope project --yes 2>&1",
            )
        ],
    )
    _registry(
        paths.registry,
        "pc-delegate@mp",
        "project",
        "/ws/pinky-agentic-plugins",
        "2026-09-17T23:52:04.206Z",
    )

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.plugin_id == "pc-delegate@mp"
    assert entry.origin == plugin_provenance.Origin(
        session_id="64197f4f",
        cwd="/ws/pinky-agentic-plugins",
        command="claude plugin install pc-delegate@mp --scope project --yes 2>&1",
        timestamp="2026-09-17T23:52:02.432Z",
    )


def test_no_matching_command_means_a_hook_or_script(paths):
    _transcript(paths.projects, "s1", "/ws", [("2026-09-17T10:00:00.000Z", "ls")])
    _registry(paths.registry, "pc-git@mp", "project", "/ws", "2026-09-17T23:52:04.206Z")

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.origin is None


def test_a_command_for_another_plugin_is_not_a_match(paths):
    _transcript(
        paths.projects,
        "s1",
        "/ws",
        [
            (
                "2026-09-17T23:52:02.000Z",
                "claude plugin install pc-core@mp --scope project",
            )
        ],
    )
    _registry(paths.registry, "pc-git@mp", "project", "/ws", "2026-09-17T23:52:04.000Z")

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.origin is None


def test_a_command_far_from_the_install_time_is_not_a_match(paths):
    _transcript(
        paths.projects,
        "s1",
        "/ws",
        [
            (
                "2026-09-17T23:30:00.000Z",
                "claude plugin install pc-git@mp --scope project",
            )
        ],
    )
    _registry(paths.registry, "pc-git@mp", "project", "/ws", "2026-09-17T23:52:04.000Z")

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.origin is None


def test_the_closest_command_wins(paths):
    _transcript(
        paths.projects,
        "s1",
        "/ws",
        [
            (
                "2026-09-17T23:50:30.000Z",
                "claude plugin install pc-git@mp --scope user",
            ),
            (
                "2026-09-17T23:52:03.000Z",
                "claude plugin install pc-git@mp --scope project",
            ),
        ],
    )
    _registry(paths.registry, "pc-git@mp", "project", "/ws", "2026-09-17T23:52:04.000Z")

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.origin.command.endswith("--scope project")


def test_a_pinky_run_is_attributed_through_its_command(paths):
    _transcript(
        paths.projects,
        "s2",
        "/ws/pinky-bootstrap",
        [("2026-09-19T13:05:30.000Z", "uv run pinky install --plugin pc-git --force")],
    )
    _registry(paths.registry, "pc-git@mp", "user", None, "2026-09-19T13:05:38.457Z")

    [entry] = plugin_provenance.registry_origins(paths.registry, paths.projects)

    assert entry.origin.session_id == "s2"
    assert "pinky install" in entry.origin.command


def test_the_report_names_the_session_or_says_nothing_was_found(paths):
    _transcript(
        paths.projects,
        "64197f4f-aaaa",
        "/ws/repo",
        [("2026-09-17T23:52:02.000Z", "claude plugin install pc-a@mp --scope project")],
    )
    paths.registry.write_text(
        json.dumps(
            {
                "plugins": {
                    "pc-a@mp": [
                        {
                            "scope": "project",
                            "projectPath": "/ws/repo",
                            "installedAt": "2026-09-17T23:52:04.000Z",
                        }
                    ],
                    "pc-b@mp": [
                        {"scope": "user", "installedAt": "2026-09-01T08:00:00.000Z"}
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    report = plugin_provenance.format_origins(
        plugin_provenance.registry_origins(paths.registry, paths.projects)
    )

    assert report == (
        "pc-a@mp  project /ws/repo  2026-09-17 23:52\\n"
        "    session 64197f4f in /ws/repo: claude plugin install pc-a@mp --scope project\\n"
        "pc-b@mp  user  2026-09-01 08:00\\n"
        "    no matching command in the transcripts: a hook or a script"
    ).replace("\\n", "\n")
