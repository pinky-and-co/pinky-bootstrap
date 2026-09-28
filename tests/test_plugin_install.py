"""`setup/plugin_install.py` — fetch a plugin's files, then wire the `statusLine` key a plugin
manifest cannot carry.

Boundary fakes only: `subprocess.run` (the `claude` CLI), and the three home-dir paths the module
reads/writes (`_REGISTRY`, `_USER_SETTINGS`, the ledger). The functions under test stay real.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_install, state_file


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Redirect every home-dir path the module and the ledger touch into `tmp_path`."""
    registry = tmp_path / "installed_plugins.json"
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(plugin_install, "_REGISTRY", registry)
    monkeypatch.setattr(plugin_install, "_USER_SETTINGS", settings)
    monkeypatch.setattr(plugin_install, "_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(
        plugin_install, "_MARKETPLACES", tmp_path / "known_marketplaces.json"
    )
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "ledger.json")
    return tmp_path


def _write_registry(
    path: Path, key: str, install_path: Path, project_path: Path | None = None
) -> None:
    entry = {"scope": "user", "installPath": str(install_path), "version": "0.1.0"}
    if project_path is not None:
        entry.update(scope="project", projectPath=str(project_path))
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {key: [entry]},
            }
        ),
        encoding="utf-8",
    )


def _make_plugin(root: Path, *, with_subagent: bool = True) -> Path:
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "statusline.py").write_text("# main", encoding="utf-8")
    if with_subagent:
        (scripts / "subagent_statusline.py").write_text("# sub", encoding="utf-8")
    return root


def test_install_plugin_files_installs_then_updates(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or None
    )
    plugin_install.install_plugin_files("pc-statusline", "pinky-agentic-plugins")

    install_cmd, install_kw = calls[0]
    assert install_cmd == [
        "claude",
        "plugin",
        "install",
        "pc-statusline@pinky-agentic-plugins",
        "--scope",
        "user",
        "--yes",
    ]
    assert install_kw["check"] is True
    update_cmd, update_kw = calls[1]
    assert update_cmd == [
        "claude",
        "plugin",
        "update",
        "pc-statusline@pinky-agentic-plugins",
    ]
    assert update_kw["check"] is False


def test_install_plugin_files_without_marketplace_uses_bare_id(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd) or None)
    plugin_install.install_plugin_files("pc-statusline")
    assert calls[0][3] == "pc-statusline"


def test_install_plugin_files_propagates_an_install_failure(monkeypatch, capsys):
    def run(cmd, **kw):
        if kw.get("check"):
            raise subprocess.CalledProcessError(
                1, cmd, stderr="marketplace 'mp' not found\n"
            )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        plugin_install.install_plugin_files("pc-statusline", "mp")

    assert "marketplace 'mp' not found" in capsys.readouterr().err


def _record_calls(monkeypatch) -> list[tuple[list[str], dict]]:
    """Replace `subprocess.run` with a recorder; the returned list fills as `claude` is called."""
    calls: list[tuple[list[str], dict]] = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_force_refetch_removes_a_cache_dir_and_reports_true(home, monkeypatch):
    _record_calls(monkeypatch)
    install = home / "cache" / "mp" / "pc-x" / "0.1.0"
    install.mkdir(parents=True)
    (install / "SKILL.md").write_text("x", encoding="utf-8")
    _write_registry(home / "installed_plugins.json", "pc-x@mp", install)

    assert plugin_install.force_refetch("pc-x", "mp") is True
    assert not install.exists()


def test_force_refetch_refetches_at_the_registered_user_scope(home, monkeypatch):
    """The fetch happens here, not on a later install: a scope plan with nothing to change
    installs nothing, which left the cache emptied."""
    calls = _record_calls(monkeypatch)
    install = home / "cache" / "mp" / "pc-x" / "0.1.0"
    install.mkdir(parents=True)
    _write_registry(home / "installed_plugins.json", "pc-x@mp", install)

    plugin_install.force_refetch("pc-x", "mp")

    assert [(cmd, kw.get("cwd")) for cmd, kw in calls] == [
        (["claude", "plugin", "install", "pc-x@mp", "--scope", "user", "--yes"], None)
    ]


def test_force_refetch_refetches_from_the_registered_project_dir(
    home, monkeypatch, tmp_path
):
    calls = _record_calls(monkeypatch)
    install = home / "cache" / "mp" / "pc-x" / "0.1.0"
    install.mkdir(parents=True)
    project = tmp_path / "workspace"
    project.mkdir()
    _write_registry(home / "installed_plugins.json", "pc-x@mp", install, project)

    plugin_install.force_refetch("pc-x", "mp")

    assert [(cmd, kw.get("cwd")) for cmd, kw in calls] == [
        (
            ["claude", "plugin", "install", "pc-x@mp", "--scope", "project", "--yes"],
            project,
        )
    ]


def test_force_refetch_is_false_when_nothing_is_cached(home):
    (home / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {}}), encoding="utf-8"
    )
    assert plugin_install.force_refetch("pc-x", "mp") is False


def test_force_refetch_refuses_a_path_outside_the_cache_root(home, capsys):
    working_tree = home / "repos" / "pc-x"
    (working_tree / ".claude-plugin").mkdir(parents=True)
    _write_registry(home / "installed_plugins.json", "pc-x@mp", working_tree)

    assert plugin_install.force_refetch("pc-x", "mp") is False
    assert working_tree.exists()
    assert "refusing --force" in capsys.readouterr().err


def test_force_refetch_refuses_a_shallow_path_inside_the_cache(home, capsys):
    marketplace_dir = home / "cache" / "mp"
    (marketplace_dir / "pc-x" / "0.1.0").mkdir(parents=True)
    _write_registry(home / "installed_plugins.json", "pc-x@mp", marketplace_dir)

    assert plugin_install.force_refetch("pc-x", "mp") is False
    assert marketplace_dir.exists()
    assert "refusing --force" in capsys.readouterr().err


def test_force_refetch_refuses_a_cache_entry_symlinked_outside(home, capsys):
    """The `directory`-source case the docstring promises to handle: the version dir is a symlink
    to a working tree — `.resolve()` collapses it, the containment check then refuses."""
    working_tree = home / "repos" / "pc-x"
    (working_tree / ".claude-plugin").mkdir(parents=True)
    version_dir = home / "cache" / "mp" / "pc-x" / "0.1.0"
    version_dir.parent.mkdir(parents=True)
    version_dir.symlink_to(working_tree, target_is_directory=True)
    _write_registry(home / "installed_plugins.json", "pc-x@mp", version_dir)

    assert plugin_install.force_refetch("pc-x", "mp") is False
    assert working_tree.exists()
    assert version_dir.exists()
    assert "refusing --force" in capsys.readouterr().err


def test_enable_at_project_installs_from_the_target_dir(home, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or None
    )
    target = tmp_path / "pinky-lib" / "pinky-core"
    target.mkdir(parents=True)

    plugin_install.enable_at_project("pc-snow", target, "pinky-agentic-plugins")

    cmd, kw = calls[0]
    assert cmd == [
        "claude",
        "plugin",
        "install",
        "pc-snow@pinky-agentic-plugins",
        "--scope",
        "project",
        "--yes",
    ]
    assert kw["cwd"] == target
    assert kw["check"] is True


def test_enable_at_project_records_the_ledger_at_the_target(
    home, monkeypatch, tmp_path
):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)
    target = tmp_path / "pinky-core"
    plugin_install.enable_at_project("pc-snow", target, "mp")

    raw = json.loads((home / "ledger.json").read_text())
    entry = raw[f"enabledPlugins:pc-snow@mp@{target}"]
    assert entry["path"] == str(target / ".claude" / "settings.json")
    assert entry["value"] == "true"


def test_enable_at_project_without_marketplace_uses_bare_id(
    home, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd) or None)
    plugin_install.enable_at_project("pc-snow", tmp_path / "r")
    assert calls[0][3] == "pc-snow"


def test_drop_user_scope_uninstalls_the_user_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)) or None
    )
    plugin_install.drop_user_scope("pc-snow", "mp")
    cmd, kw = calls[0]
    assert cmd == [
        "claude",
        "plugin",
        "uninstall",
        "pc-snow@mp",
        "--scope",
        "user",
        "--yes",
    ]
    assert kw["check"] is True


def test_drop_user_scope_propagates_a_failure(monkeypatch):
    def run(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        plugin_install.drop_user_scope("pc-snow")


def test_resolve_install_path_reads_the_registry(home):
    plugin_dir = home / "cache" / "pc-statusline" / "0.1.0"
    plugin_dir.mkdir(parents=True)
    _write_registry(home / "installed_plugins.json", "pc-statusline@mp", plugin_dir)
    assert plugin_install.resolve_install_path("pc-statusline", "mp") == plugin_dir


def test_resolve_install_path_matches_by_id_when_no_marketplace_given(home):
    plugin_dir = home / "cache" / "pc-statusline" / "0.1.0"
    plugin_dir.mkdir(parents=True)
    _write_registry(
        home / "installed_plugins.json", "pc-statusline@whatever", plugin_dir
    )
    assert plugin_install.resolve_install_path("pc-statusline") == plugin_dir


def test_resolve_install_path_raises_when_absent(home):
    (home / "installed_plugins.json").write_text('{"plugins": {}}', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        plugin_install.resolve_install_path("pc-statusline", "mp")


def test_resolve_install_path_skips_a_stale_entry_whose_dir_is_gone(home):
    (home / "installed_plugins.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "pc-statusline@mp": [
                        {"installPath": str(home / "cache" / "gone" / "0.0.9")}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError):
        plugin_install.resolve_install_path("pc-statusline", "mp")


def test_set_status_lines_writes_both_keys_and_merges(home):
    (home / "settings.json").write_text(
        json.dumps({"theme": "custom:x", "enabledPlugins": {"a@b": True}}),
        encoding="utf-8",
    )
    plugin_dir = _make_plugin(home / "plugin")

    written = plugin_install.set_status_lines(plugin_dir)

    assert written == ["statusLine", "subagentStatusLine"]
    data = json.loads((home / "settings.json").read_text())
    assert data["theme"] == "custom:x"
    assert data["enabledPlugins"] == {"a@b": True}
    assert data["statusLine"] == {
        "type": "command",
        "command": f'python3 "{plugin_dir / "scripts" / "statusline.py"}"',
    }
    assert data["subagentStatusLine"]["command"].endswith('subagent_statusline.py"')


def test_set_status_lines_records_the_ledger(home):
    plugin_dir = _make_plugin(home / "plugin")
    plugin_install.set_status_lines(plugin_dir)
    raw = json.loads((home / "ledger.json").read_text())
    assert raw["statusLine"]["value"].endswith("statusline.py")
    assert raw["statusLine"]["path"] == str(home / "settings.json")


def test_set_status_lines_is_a_noop_for_a_plugin_without_a_status_line(home):
    plain = home / "plain-plugin"
    (plain / "skills").mkdir(parents=True)
    assert plugin_install.set_status_lines(plain) == []
    assert not (home / "settings.json").exists()


def test_set_status_lines_handles_a_plugin_with_only_the_main_script(home):
    plugin_dir = _make_plugin(home / "plugin", with_subagent=False)
    assert plugin_install.set_status_lines(plugin_dir) == ["statusLine"]
    data = json.loads((home / "settings.json").read_text())
    assert "subagentStatusLine" not in data


def test_ships_lsp_server_true_when_a_dot_lsp_json_file_is_present(tmp_path):
    plugin_dir = tmp_path / "pyright"
    plugin_dir.mkdir()
    (plugin_dir / ".lsp.json").write_text("{}", encoding="utf-8")
    assert plugin_install.ships_lsp_server(plugin_dir) is True


def test_ships_lsp_server_false_for_a_plugin_without_one(tmp_path):
    plugin_dir = tmp_path / "plain"
    (plugin_dir / "skills").mkdir(parents=True)
    assert plugin_install.ships_lsp_server(plugin_dir) is False


def test_lsp_server_commands_reads_the_command_of_every_language_entry(tmp_path):
    plugin_dir = tmp_path / "pyright"
    plugin_dir.mkdir()
    (plugin_dir / ".lsp.json").write_text(
        json.dumps(
            {
                "python": {"command": "pyright-langserver", "args": ["--stdio"]},
                "pyi": {"command": "pyright-langserver", "args": ["--stdio"]},
            }
        ),
        encoding="utf-8",
    )
    assert plugin_install.lsp_server_commands(plugin_dir) == {"pyright-langserver"}


def test_lsp_server_commands_empty_for_a_plugin_without_lsp_json(tmp_path):
    plugin_dir = tmp_path / "plain"
    plugin_dir.mkdir()
    assert plugin_install.lsp_server_commands(plugin_dir) == set()


def test_lsp_server_commands_tolerates_malformed_json(tmp_path):
    plugin_dir = tmp_path / "broken"
    plugin_dir.mkdir()
    (plugin_dir / ".lsp.json").write_text("not json", encoding="utf-8")
    assert plugin_install.lsp_server_commands(plugin_dir) == set()


def test_ensure_lsp_tool_enabled_writes_env_at_user_scope(home):
    plugin_install.ensure_lsp_tool_enabled()
    data = json.loads((home / "settings.json").read_text())
    assert data["env"] == {"ENABLE_LSP_TOOL": "1"}


def test_ensure_lsp_tool_enabled_preserves_existing_keys_and_env_vars(home):
    (home / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"pc-snow@mp": True}, "env": {"OTHER_VAR": "x"}}),
        encoding="utf-8",
    )
    plugin_install.ensure_lsp_tool_enabled()
    data = json.loads((home / "settings.json").read_text())
    assert data["enabledPlugins"] == {"pc-snow@mp": True}
    assert data["env"] == {"OTHER_VAR": "x", "ENABLE_LSP_TOOL": "1"}


def test_ensure_lsp_tool_enabled_records_the_ledger(home):
    plugin_install.ensure_lsp_tool_enabled()
    raw = json.loads((home / "ledger.json").read_text())
    entry = raw["env.ENABLE_LSP_TOOL@user"]
    assert entry["path"] == str(home / "settings.json")
    assert entry["value"] == "1"


def _seed_two_marketplaces(home: Path) -> None:
    """`pc-a` from a local `directory` marketplace, `pc-b` from a GitHub one, both cached."""
    entries = {}
    for key in ("pc-a@local", "pc-b@remote"):
        name, mp = key.split("@")
        install = home / "cache" / mp / name / "0.1.0"
        install.mkdir(parents=True)
        entries[key] = [
            {"scope": "user", "installPath": str(install), "version": "0.1.0"}
        ]
    (home / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": entries}), encoding="utf-8"
    )
    (home / "known_marketplaces.json").write_text(
        json.dumps(
            {
                "local": {"source": {"source": "directory", "path": "/src/local"}},
                "remote": {"source": {"source": "github", "repo": "o/r"}},
            }
        ),
        encoding="utf-8",
    )


def test_refresh_with_no_name_refreshes_only_local_marketplace_plugins(
    home, monkeypatch
):
    calls = _record_calls(monkeypatch)
    _seed_two_marketplaces(home)

    outcomes = plugin_install.refresh_plugins([])

    assert outcomes == [plugin_install.RefreshOutcome("pc-a@local", "refreshed")]
    assert [cmd[3] for cmd, _ in calls] == ["pc-a@local"]


def test_refresh_named_plugin_resolves_its_marketplace(home, monkeypatch):
    _record_calls(monkeypatch)
    _seed_two_marketplaces(home)

    outcomes = plugin_install.refresh_plugins(["pc-b"])

    assert outcomes == [plugin_install.RefreshOutcome("pc-b", "refreshed")]


def test_refresh_reports_a_plugin_that_is_not_installed(home, monkeypatch):
    calls = _record_calls(monkeypatch)
    _seed_two_marketplaces(home)

    outcomes = plugin_install.refresh_plugins(["pc-nope"])

    assert outcomes == [plugin_install.RefreshOutcome("pc-nope", "absent")]
    assert calls == []


def test_refresh_keeps_going_after_a_failed_fetch(home, monkeypatch, capsys):
    def fake_run(cmd, **kw):
        if cmd[3] == "pc-a@local":
            raise subprocess.CalledProcessError(1, cmd, "", "boom\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _seed_two_marketplaces(home)

    outcomes = plugin_install.refresh_plugins(["pc-a", "pc-b"])

    assert outcomes == [
        plugin_install.RefreshOutcome("pc-a", "failed"),
        plugin_install.RefreshOutcome("pc-b", "refreshed"),
    ]
    assert "boom" in capsys.readouterr().err


def test_render_refresh_report():
    """Whole-string oracle, color off — the report a pipe or a test runner sees."""
    outcomes = [
        plugin_install.RefreshOutcome("pc-git", "refreshed"),
        plugin_install.RefreshOutcome("pc-nope", "absent"),
        plugin_install.RefreshOutcome("pc-core", "failed"),
    ]
    assert plugin_install.render_refresh_report(outcomes) == (
        "✓ pc-git   refreshed\n"
        "• pc-nope  not installed — nothing to refresh\n"
        "✗ pc-core  fetch failed (see the error above)\n"
        "\n"
        "Running sessions keep the old build until /reload-plugins."
    )


def test_render_refresh_report_paints_only_when_color_is_on():
    outcomes = [plugin_install.RefreshOutcome("pc-git", "refreshed")]
    painted = plugin_install.render_refresh_report(outcomes, color=True)
    assert painted.startswith("\x1b[32m✓\x1b[0m pc-git"), painted


def test_render_refresh_report_when_nothing_matched():
    assert plugin_install.render_refresh_report([]) == (
        "nothing to refresh — no plugin installed from a local (directory) marketplace"
    )
