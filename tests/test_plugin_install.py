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
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "ledger.json")
    return tmp_path


def _write_registry(path: Path, key: str, install_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    key: [
                        {
                            "scope": "user",
                            "installPath": str(install_path),
                            "version": "0.1.0",
                        }
                    ]
                },
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


# --- install_plugin_files -----------------------------------------------------------------


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
    # update is best-effort — it must not abort the flow on a fresh plugin
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


def test_install_plugin_files_propagates_an_install_failure(monkeypatch):
    def run(cmd, **kw):
        if kw.get("check"):
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        plugin_install.install_plugin_files("pc-statusline", "mp")


# --- resolve_install_path ----------------------------------------------------------------


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


# --- set_status_lines -------------------------------------------------------------------


def test_set_status_lines_writes_both_keys_and_merges(home):
    (home / "settings.json").write_text(
        json.dumps({"theme": "custom:x", "enabledPlugins": {"a@b": True}}),
        encoding="utf-8",
    )
    plugin_dir = _make_plugin(home / "plugin")

    written = plugin_install.set_status_lines(plugin_dir)

    assert written == ["statusLine", "subagentStatusLine"]
    data = json.loads((home / "settings.json").read_text())
    # untouched keys survive
    assert data["theme"] == "custom:x"
    assert data["enabledPlugins"] == {"a@b": True}
    # both status-line keys point at the installed scripts
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
