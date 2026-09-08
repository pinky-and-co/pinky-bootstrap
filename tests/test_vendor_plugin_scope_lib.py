"""`hygiene/vendor/plugin_scope_lib.py` — plugin discovery for the cwd-scope hook.

Vendored source of truth, distributed into pc-core/hooks and pc-kanban/chantier.
`matching_plugin_ids` decides which project-scoped plugins a descent into a
directory should enable; `settings_local_plugin_ids` and `enable_plugin_local`'s
`already_enabled` flag keep the descent from re-enabling what is already on.

Boundary fake only: `subprocess.run` (the `claude` CLI) is replaced per-test.
`installed_plugins.json` is passed in as a dict — the parse is trivial and
covered by its own tolerant loader elsewhere.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hygiene" / "vendor"))
import plugin_scope_lib as psl


def _installed(**plugins: list[dict]) -> dict:
    return {"plugins": dict(plugins)}


# ── matching_plugin_ids — user scope ────────────────────────────────────────


def test_a_plugin_with_a_user_scope_entry_is_never_matched(tmp_path):
    ws = tmp_path
    (ws / "ops").mkdir()
    installed = _installed(
        **{
            "pc-core@mp": [
                {"scope": "user"},
                {"scope": "project", "projectPath": str(ws / "ops")},
            ]
        }
    )
    assert psl.matching_plugin_ids(ws / "ops", installed) == []


# ── matching_plugin_ids — the descend / ascend split via open_path ──────────


def test_project_plugin_below_open_path_is_matched_on_descend(tmp_path):
    ws = tmp_path
    deep = ws / "pinky-lib" / "pinky-ai" / "tests"
    deep.mkdir(parents=True)
    installed = _installed(
        **{
            "pc-snow@mp": [
                {"scope": "project", "projectPath": str(ws / "pinky-lib" / "pinky-ai")}
            ]
        }
    )
    assert psl.matching_plugin_ids(deep, installed, open_path=ws) == ["pc-snow@mp"]


def test_project_plugin_at_or_above_open_path_is_excluded_on_descend(tmp_path):
    ws = tmp_path
    (ws / "ops" / "sub").mkdir(parents=True)
    installed = _installed(
        **{
            "at-open@mp": [{"scope": "project", "projectPath": str(ws / "ops")}],
            "above-open@mp": [{"scope": "project", "projectPath": str(ws)}],
        }
    )
    assert (
        psl.matching_plugin_ids(ws / "ops" / "sub", installed, open_path=ws / "ops")
        == []
    )


def test_without_open_path_the_ascend_still_sees_plugins_at_that_path(tmp_path):
    ws = tmp_path
    (ws / "ops").mkdir()
    installed = _installed(
        **{"pc-craft@mp": [{"scope": "project", "projectPath": str(ws / "ops")}]}
    )
    # l'ascend du SessionStart n'a pas d'open_path : il doit activer ce plugin
    assert psl.matching_plugin_ids(ws / "ops", installed) == ["pc-craft@mp"]


def test_local_scope_entries_are_not_a_discovery_source(tmp_path):
    ws = tmp_path
    (ws / "ops").mkdir()
    installed = _installed(
        **{"loc@mp": [{"scope": "local", "projectPath": str(ws / "ops")}]}
    )
    assert psl.matching_plugin_ids(ws / "ops", installed, open_path=ws) == []


# ── settings_local_plugin_ids ──────────────────────────────────────────────


def test_settings_local_plugin_ids_returns_every_listed_id_on_or_off(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"b@mp": False, "a@mp": True}})
    )
    assert psl.settings_local_plugin_ids(tmp_path) == ["a@mp", "b@mp"]


def test_settings_local_plugin_ids_absent_file_is_empty(tmp_path):
    assert psl.settings_local_plugin_ids(tmp_path) == []


def test_settings_local_plugin_ids_malformed_json_is_empty(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.local.json").write_text("{not json")
    assert psl.settings_local_plugin_ids(tmp_path) == []


# ── enable_plugin_local — already_enabled vs real failure ──────────────────


def _fake_run(returncode: int, stderr: str):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return run


def test_enable_plugin_local_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, ""))
    result = psl.enable_plugin_local("x@mp")
    assert result == psl.EnableResult(success=True, already_enabled=False, stderr="")


def test_enable_plugin_local_already_enabled_is_not_a_failure(monkeypatch):
    stderr = '✘ Failed to enable plugin "x@mp": Plugin "x@mp" is already enabled at local scope'
    monkeypatch.setattr(subprocess, "run", _fake_run(1, stderr))
    result = psl.enable_plugin_local("x@mp")
    assert result.success is False
    assert result.already_enabled is True


def test_enable_plugin_local_real_error_is_a_failure(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(1, "marketplace not found"))
    result = psl.enable_plugin_local("x@mp")
    assert result.success is False
    assert result.already_enabled is False


def test_enable_plugin_local_missing_cli_is_a_failure(monkeypatch):
    def boom(*_a, **_kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)
    result = psl.enable_plugin_local("x@mp")
    assert result == psl.EnableResult(
        success=False, already_enabled=False, stderr="claude"
    )
