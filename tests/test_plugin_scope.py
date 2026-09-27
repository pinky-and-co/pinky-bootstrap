"""`setup/plugin_scope.py` — which directories a plugin gets enabled at.

`enabledPlugins` scopes by directory, not always user-level. The
wizard picks the targets; the enable is `claude plugin install --scope project` run from each one.

Boundary fake only: `subprocess.run` (the `claude` CLI) is replaced by `_ClaudeCliSim`, which
reproduces the measured filesystem effect of `claude plugin install/uninstall` —
`--scope user` writes `~/.claude/settings.json`, `--scope project` writes `<cwd>/.claude/
settings.json`, `uninstall --scope user` removes the user key. `run_marketplace_wizard` stays real.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_install, state_file
from setup.plugin_scope import (
    IGNORE_MARKER,
    list_targets_at_depth,
    run_marketplace_wizard,
)


def _canned_input(monkeypatch, answers):
    """`input()` returns each of `answers` in order, one per call — no real terminal needed."""
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _make_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()


def _workspace(tmp_path: Path) -> Path:
    """bootstrap/ (repo directly) + pinky-lib/ (group, 2 nested repos) + a dotfile dir to ignore."""
    root = tmp_path / "workspace"
    _make_repo(root / "bootstrap")
    _make_repo(root / "pinky-lib" / "pinky-core")
    _make_repo(root / "pinky-lib" / "pinky-snowpark")
    (root / ".hidden").mkdir(parents=True)
    return root


def _enabled(settings_json: Path) -> dict:
    if not settings_json.is_file():
        return {}
    return json.loads(settings_json.read_text(encoding="utf-8")).get(
        "enabledPlugins", {}
    )


class _ClaudeCliSim:
    """Faithful stand-in for `claude plugin …` — reproduces the measured on-disk effect so a test
    proves the whole chain, not a mock of it. Records every argv+cwd for oracle assertions."""

    def __init__(self, fake_home: Path):
        self.fake_home = fake_home
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd, **kw):
        cwd = Path(kw["cwd"]) if kw.get("cwd") else None
        self.calls.append((list(cmd), cwd))
        if cmd[:3] == ["claude", "plugin", "install"]:
            spec = cmd[3]
            scope = cmd[cmd.index("--scope") + 1]
            root = self.fake_home if scope == "user" else cwd
            self._toggle(root / ".claude" / "settings.json", spec, on=True)
        elif cmd[:3] == ["claude", "plugin", "uninstall"]:
            spec = cmd[3]
            scope = cmd[cmd.index("--scope") + 1]
            root = self.fake_home if scope == "user" else cwd
            self._toggle(root / ".claude" / "settings.json", spec, on=False)

        return subprocess.CompletedProcess(cmd, 0)

    @staticmethod
    def _toggle(settings: Path, spec: str, *, on: bool) -> None:
        settings.parent.mkdir(parents=True, exist_ok=True)
        data = (
            json.loads(settings.read_text(encoding="utf-8"))
            if settings.is_file()
            else {}
        )
        enabled = data.setdefault("enabledPlugins", {})
        if on:
            enabled[spec] = True
        else:
            enabled.pop(spec, None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def sim(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setattr(
        plugin_install, "_USER_SETTINGS", fake_home / ".claude" / "settings.json"
    )
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    cli = _ClaudeCliSim(fake_home)
    monkeypatch.setattr(subprocess, "run", cli)
    return cli


def test_depth_0_is_the_workspace_root_itself(tmp_path):
    root = _workspace(tmp_path)
    assert list_targets_at_depth(root, depth=0) == [root]


def test_depth_1_lists_top_level_groups_only(tmp_path):
    root = _workspace(tmp_path)
    targets = list_targets_at_depth(root, depth=1)
    assert {p.name for p in targets} == {"pinky-lib"}


def test_depth_1_ignores_dotfile_directories(tmp_path):
    root = _workspace(tmp_path)
    assert ".hidden" not in {p.name for p in list_targets_at_depth(root, depth=1)}


def test_depth_1_ignores_a_directory_marked_with_pinky_ignore(tmp_path):
    """`_BACKUP_READ-ONLY`-shaped case: a read-only backup mount, named however the workspace
    owner likes, is excluded by the marker alone — no name is hard-coded."""
    root = _workspace(tmp_path)
    backup = root / "_BACKUP_READ-ONLY"
    _make_repo(backup / "bootstrap")
    (backup / IGNORE_MARKER).touch()

    assert "_BACKUP_READ-ONLY" not in {
        p.name for p in list_targets_at_depth(root, depth=1)
    }


def test_depth_2_ignores_repos_under_a_marked_directory(tmp_path):
    root = _workspace(tmp_path)
    backup = root / "_BACKUP_READ-ONLY"
    _make_repo(backup / "bootstrap")
    (backup / IGNORE_MARKER).touch()

    targets = list_targets_at_depth(root, depth=2)

    assert {p.name for p in targets} == {"bootstrap", "pinky-core", "pinky-snowpark"}


def test_a_marked_repo_itself_is_also_excluded(tmp_path):
    """The marker wins even on a directory that is itself a git repo — a read-only checkout
    under backup is still a repo by `_is_repo`'s own test, but must not become a target."""
    root = _workspace(tmp_path)
    backup_repo = root / "bootstrap-backup"
    _make_repo(backup_repo)
    (backup_repo / IGNORE_MARKER).touch()

    targets = list_targets_at_depth(root, depth=2)

    assert "bootstrap-backup" not in {p.name for p in targets}


def test_depth_2_lists_every_repo_regardless_of_nesting(tmp_path):
    root = _workspace(tmp_path)
    targets = list_targets_at_depth(root, depth=2)

    assert {p.name for p in targets} == {"bootstrap", "pinky-core", "pinky-snowpark"}


def test_unsupported_depth_raises(tmp_path):
    with pytest.raises(ValueError):
        list_targets_at_depth(_workspace(tmp_path), depth=3)


def test_wizard_project_scope_enables_at_the_single_picked_target(
    sim, tmp_path, monkeypatch
):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "0"])

    roots = run_marketplace_wizard(root_ws, "pc-snow")

    assert roots == [root_ws / "bootstrap"]
    assert _enabled(root_ws / "bootstrap" / ".claude" / "settings.json") == {
        "pc-snow": True
    }

    assert not any("user" in c for c, _ in sim.calls)


def test_wizard_project_scope_never_touches_other_targets(sim, tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "1"])

    run_marketplace_wizard(root_ws, "pc-snow", "pinky-agentic-plugins")

    assert _enabled(
        root_ws / "pinky-lib" / "pinky-core" / ".claude" / "settings.json"
    ) == {"pc-snow@pinky-agentic-plugins": True}
    assert not (
        root_ws / "pinky-lib" / "pinky-snowpark" / ".claude" / "settings.json"
    ).exists()


def test_wizard_project_scope_multi_target_enables_at_each(sim, tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "1 2"])

    roots = run_marketplace_wizard(root_ws, "pc-snow", "mp")

    assert {r.name for r in roots} == {"pinky-core", "pinky-snowpark"}
    for name in ("pinky-core", "pinky-snowpark"):
        assert _enabled(root_ws / "pinky-lib" / name / ".claude" / "settings.json") == {
            "pc-snow@mp": True
        }


def test_wizard_multi_target_accepts_comma_separated_indices(
    sim, tmp_path, monkeypatch
):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "0,1"])

    roots = run_marketplace_wizard(root_ws, "pc-snow")

    assert {r.name for r in roots} == {"bootstrap", "pinky-core"}


def test_wizard_project_scope_call_sequence_is_pinned(sim, tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "1 2"])

    run_marketplace_wizard(root_ws, "pc-snow", "mp")

    core = root_ws / "pinky-lib" / "pinky-core"
    snow = root_ws / "pinky-lib" / "pinky-snowpark"

    assert sim.calls == [
        (
            [
                "claude",
                "plugin",
                "install",
                "pc-snow@mp",
                "--scope",
                "project",
                "--yes",
            ],
            core,
        ),
        (
            [
                "claude",
                "plugin",
                "install",
                "pc-snow@mp",
                "--scope",
                "project",
                "--yes",
            ],
            snow,
        ),
    ]


def test_wizard_user_scope_issues_no_claude_call_at_all(sim, tmp_path, monkeypatch):
    _canned_input(monkeypatch, ["u"])
    roots = run_marketplace_wizard(_workspace(tmp_path), "pc-statusline")
    assert roots == [tmp_path / "home"]
    assert sim.calls == []


def test_wizard_non_interactive_shell_errors_instead_of_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SystemExit):
        run_marketplace_wizard(tmp_path, "pc-statusline")


def test_wizard_unknown_scope_answer_errors(sim, tmp_path, monkeypatch):
    _canned_input(monkeypatch, ["nonsense"])
    with pytest.raises(SystemExit):
        run_marketplace_wizard(tmp_path, "pc-statusline")


def test_wizard_out_of_range_target_index_errors(sim, tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "1", "9"])
    with pytest.raises(SystemExit):
        run_marketplace_wizard(root_ws, "pc-snow")


def test_wizard_empty_target_pick_errors(sim, tmp_path, monkeypatch):
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "1", "  "])
    with pytest.raises(SystemExit):
        run_marketplace_wizard(root_ws, "pc-snow")


def _lsp_plugin(tmp_path: Path) -> Path:
    plugin_dir = tmp_path / "installed" / "pyright"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / ".lsp.json").write_text("{}", encoding="utf-8")
    return plugin_dir


def test_wizard_project_scope_wires_lsp_tool_env_at_user_scope(
    sim, tmp_path, monkeypatch
):
    root_ws = _workspace(tmp_path)
    install_path = _lsp_plugin(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "0"])

    run_marketplace_wizard(
        root_ws, "pyright", "claude-code-lsps", install_path=install_path
    )

    home_settings = json.loads(
        (tmp_path / "home" / ".claude" / "settings.json").read_text()
    )
    assert home_settings["env"] == {"ENABLE_LSP_TOOL": "1"}
    project_settings = json.loads(
        (root_ws / "bootstrap" / ".claude" / "settings.json").read_text()
    )
    assert "env" not in project_settings


def test_wizard_project_scope_skips_lsp_env_without_install_path(
    sim, tmp_path, monkeypatch
):
    """No `install_path` given (existing callers, unchanged) — never guess, never write it."""
    root_ws = _workspace(tmp_path)
    _canned_input(monkeypatch, ["p", "2", "0"])

    run_marketplace_wizard(root_ws, "pc-snow")

    data = json.loads((root_ws / "bootstrap" / ".claude" / "settings.json").read_text())
    assert "env" not in data


def test_wizard_project_scope_skips_lsp_env_for_a_plugin_without_one(
    sim, tmp_path, monkeypatch
):
    root_ws = _workspace(tmp_path)
    plain = tmp_path / "installed" / "pc-snow"
    plain.mkdir(parents=True)
    _canned_input(monkeypatch, ["p", "2", "0"])

    run_marketplace_wizard(root_ws, "pc-snow", install_path=plain)

    data = json.loads((root_ws / "bootstrap" / ".claude" / "settings.json").read_text())
    assert "env" not in data


def test_wizard_user_scope_wires_lsp_tool_env_when_the_plugin_ships_one(
    sim, tmp_path, monkeypatch
):
    install_path = _lsp_plugin(tmp_path)
    _canned_input(monkeypatch, ["u"])

    run_marketplace_wizard(
        _workspace(tmp_path), "pyright", "claude-code-lsps", install_path=install_path
    )

    data = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_text())
    assert data["env"] == {"ENABLE_LSP_TOOL": "1"}


def test_wizard_wires_lsp_tool_env_once_for_several_targets(sim, tmp_path, monkeypatch):
    """`ENABLE_LSP_TOOL` is one user-scope key — enabling the plugin at several project targets
    writes it once, not once per target (it used to sit inside the per-target loop)."""
    root_ws = _workspace(tmp_path)
    install_path = _lsp_plugin(tmp_path)
    calls: list[int] = []
    real = plugin_install.ensure_lsp_tool_enabled
    monkeypatch.setattr(
        plugin_install,
        "ensure_lsp_tool_enabled",
        lambda: (calls.append(1), real())[1],
    )
    _canned_input(monkeypatch, ["p", "2", "1 2"])

    roots = run_marketplace_wizard(
        root_ws, "pyright", "claude-code-lsps", install_path=install_path
    )

    assert len(roots) == 2
    assert calls == [1]
