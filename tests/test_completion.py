"""Shell completion: subjects, verbs, options and plugin names, driven through `argcomplete`.

`argcomplete` reads the shell's `COMP_LINE`/`COMP_POINT` and writes the candidates to a stream;
these tests play the shell's part so the completion of the real `pinky` parser is what is asserted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_catalog


_SCRIPT = (
    "import sys, argcomplete\n"
    "from setup import cli_pinky\n"
    "argcomplete.autocomplete(cli_pinky.build_parser(), exit_method=sys.exit, output_stream=sys.stdout)\n"
)


def _complete(line: str, home: Path | None = None) -> list[str]:
    """What the shell would offer after `line` — the real `pinky` parser, run in a child process
    because `argcomplete` closes file descriptors the test runner still needs."""
    env = {
        **os.environ,
        "_ARGCOMPLETE": "1",
        "_ARGCOMPLETE_IFS": "\n",
        "COMP_LINE": line,
        "COMP_POINT": str(len(line)),
    }
    if home is not None:
        # `Path.home()` reads HOME on POSIX and USERPROFILE on Windows
        env["HOME"] = env["USERPROFILE"] = str(home)
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        env=env,
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    # argcomplete ends a unique candidate with a space, the shell's "word finished" marker
    return [
        candidate.strip()
        for candidate in result.stdout.split("\n")
        if candidate.strip()
    ]


@pytest.fixture
def claude_dir(tmp_path):
    """A fake HOME whose `~/.claude` has two installed plugins and one marketplace publishing a
    plugin that is not installed. Returns the HOME."""
    home = tmp_path / "home" / ".claude"
    (home / "plugins").mkdir(parents=True)
    (home / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "pc-git@mp": [{"scope": "user"}],
                    "pc-core@mp": [{"scope": "project", "projectPath": "/ws"}],
                }
            }
        ),
        encoding="utf-8",
    )
    catalog = tmp_path / "mp" / ".claude-plugin"
    catalog.mkdir(parents=True)
    (catalog / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "pc-git"}, {"name": "pc-snow"}]}),
        encoding="utf-8",
    )
    (home / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": str(tmp_path / "mp")}}), encoding="utf-8"
    )
    return home.parent


def test_the_subjects_are_completed():
    assert set(_complete("pinky ")) >= {
        "claude-plugin",
        "live-docs",
        "repo",
        "install",
        "doctor",
        "directives",
    }


def test_a_subjects_verbs_are_completed():
    assert set(_complete("pinky claude-plugin ")) >= {"install", "list", "reconcile"}
    assert set(_complete("pinky repo ")) >= {"new", "distribute", "drift", "llm-drift"}


def test_an_options_are_completed():
    assert "--marketplace" in _complete("pinky claude-plugin install --")


def test_installed_and_catalog_plugin_names_are_completed(claude_dir):
    assert set(_complete("pinky claude-plugin install pc-", claude_dir)) == {
        "pc-core",
        "pc-git",
        "pc-snow",
    }


def test_the_prefix_narrows_the_plugin_names(claude_dir):
    assert _complete("pinky claude-plugin install pc-s", claude_dir) == ["pc-snow"]


def test_marketplace_names_are_completed(claude_dir):
    assert _complete(
        "pinky claude-plugin install pc-x --marketplace m", claude_dir
    ) == ["mp"]


def test_a_missing_claude_dir_completes_nothing_and_does_not_fail(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(plugin_catalog, "CLAUDE_DIR", tmp_path / "absent")
    assert plugin_catalog.known_plugin_names() == []
    assert plugin_catalog.known_marketplace_names() == []


def test_runtime_dependencies_are_exactly_the_declared_allowlist():
    """Every runtime dependency this repo takes is a deliberate one, not an accidental transitive
    pull: `argcomplete` (shell completion) and `questionary` (the interactive checkbox picker,
    `setup/tui.py` — see `docs/adr/0008-questionary-interactive-picker.md`)."""
    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )

    names = {
        dep.split(">=")[0].split("==")[0]
        for dep in pyproject["project"]["dependencies"]
    }
    assert names == {"argcomplete", "questionary"}
