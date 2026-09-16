"""`hygiene/vendor/plugin_scope_lib.py` — plugin discovery for the cwd-scope hook.

Vendored source of truth, distributed into pc-autodiscovery/hooks and
pc-kanban (chantier + spawn-workers).
`matching_plugin_ids` decides which project-scoped plugins a descent into a
directory should enable; `settings_local_plugin_ids` and `enable_plugin_local`'s
`already_enabled` flag keep the descent from re-enabling what is already on.

Boundary fake only: `subprocess.run` (the `claude` CLI) is replaced per-test.
`installed_plugins.json` is passed in as a dict — the parse is trivial and
covered by its own tolerant loader elsewhere.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hygiene" / "vendor"))
import plugin_scope_lib as psl


def _installed(**plugins: list[dict]) -> dict:
    return {"plugins": dict(plugins)}


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

    assert psl.matching_plugin_ids(ws / "ops", installed) == ["pc-craft@mp"]


def test_local_scope_entries_are_not_a_discovery_source(tmp_path):
    ws = tmp_path
    (ws / "ops").mkdir()
    installed = _installed(
        **{"loc@mp": [{"scope": "local", "projectPath": str(ws / "ops")}]}
    )
    assert psl.matching_plugin_ids(ws / "ops", installed, open_path=ws) == []


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


def _fake_run(returncode: int, stderr: str, calls: list | None = None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    return run


def test_enable_plugin_local_runs_claude_from_the_given_cwd(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "", calls))
    psl.enable_plugin_local("x@mp", cwd=tmp_path)
    cmd, kw = calls[0]
    assert cmd == ["claude", "plugin", "enable", "-s", "local", "x@mp"]
    assert kw["cwd"] == tmp_path


def test_enable_plugin_local_success(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, ""))
    result = psl.enable_plugin_local("x@mp", cwd=tmp_path)
    assert result == psl.EnableResult(success=True, already_enabled=False, stderr="")


def test_enable_plugin_local_already_enabled_is_not_a_failure(monkeypatch, tmp_path):
    stderr = '✘ Failed to enable plugin "x@mp": Plugin "x@mp" is already enabled at local scope'
    monkeypatch.setattr(subprocess, "run", _fake_run(1, stderr))
    result = psl.enable_plugin_local("x@mp", cwd=tmp_path)
    assert result.success is False
    assert result.already_enabled is True


def test_enable_plugin_local_real_error_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run(1, "marketplace not found"))
    result = psl.enable_plugin_local("x@mp", cwd=tmp_path)
    assert result.success is False
    assert result.already_enabled is False


def test_enable_plugin_local_missing_cli_is_a_failure(monkeypatch, tmp_path):
    def boom(*_a, **_kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)
    result = psl.enable_plugin_local("x@mp", cwd=tmp_path)
    assert result == psl.EnableResult(
        success=False, already_enabled=False, stderr="claude"
    )


def test_install_plugin_project_runs_claude_from_the_given_cwd(monkeypatch, tmp_path):
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _fake_run(0, "", calls))
    psl.install_plugin_project("x@mp", cwd=tmp_path)
    cmd, kw = calls[0]
    assert cmd == ["claude", "plugin", "install", "x@mp", "--scope", "project", "--yes"]
    assert kw["cwd"] == tmp_path


def test_install_plugin_project_success(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run(0, ""))
    result = psl.install_plugin_project("x@mp", cwd=tmp_path)
    assert result == psl.EnableResult(success=True, already_enabled=False, stderr="")


def test_install_plugin_project_real_error_is_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", _fake_run(1, "marketplace not found"))
    result = psl.install_plugin_project("x@mp", cwd=tmp_path)
    assert result.success is False
    assert result.already_enabled is False


def test_install_plugin_project_missing_cli_is_a_failure(monkeypatch, tmp_path):
    def boom(*_a, **_kw):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(subprocess, "run", boom)
    result = psl.install_plugin_project("x@mp", cwd=tmp_path)
    assert result == psl.EnableResult(
        success=False, already_enabled=False, stderr="claude"
    )


def test_settings_json_plugin_ids_returns_every_listed_id_on_or_off(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"b@mp": False, "a@mp": True}})
    )
    assert psl.settings_json_plugin_ids(tmp_path) == ["a@mp", "b@mp"]


def test_settings_json_plugin_ids_absent_file_is_empty(tmp_path):
    assert psl.settings_json_plugin_ids(tmp_path) == []


def test_settings_json_plugin_ids_malformed_json_is_empty(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{not json")
    assert psl.settings_json_plugin_ids(tmp_path) == []


def test_project_scope_installed_ids_matches_only_the_exact_path(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    installed = _installed(
        **{
            "here@mp": [{"scope": "project", "projectPath": str(repo)}],
            "ancestor@mp": [{"scope": "project", "projectPath": str(tmp_path)}],
        }
    )
    monkeypatch.setattr(psl, "load_installed_plugins", lambda: installed)
    assert psl.project_scope_installed_ids(repo) == ["here@mp"]


def _use_state_dir(monkeypatch, tmp_path):
    state_dir = tmp_path / "state"
    monkeypatch.setattr(psl, "STATE_DIR", state_dir)
    return state_dir


def test_shared_backup_second_session_joins_without_recapturing(monkeypatch, tmp_path):
    _use_state_dir(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings_local = repo / ".claude" / "settings.local.json"
    settings_local.write_text(json.dumps({"enabledPlugins": {"orig@mp": True}}))

    psl.backup_settings_local_shared(settings_local, "A", os.getpid())
    settings_local.write_text(
        json.dumps({"enabledPlugins": {"orig@mp": True, "cwd-written@mp": True}})
    )
    psl.backup_settings_local_shared(
        settings_local, "B", os.getpid()
    )  # ne doit pas recapturer

    psl.restore_settings_local_shared(settings_local, "A")
    assert json.loads(settings_local.read_text())["enabledPlugins"] == {
        "orig@mp": True,
        "cwd-written@mp": True,
    }  # B encore vivante — pas de restauration

    psl.restore_settings_local_shared(settings_local, "B")
    assert json.loads(settings_local.read_text()) == {
        "enabledPlugins": {"orig@mp": True}
    }


def test_shared_backup_lifo_and_non_lifo_close_both_restore(monkeypatch, tmp_path):
    _use_state_dir(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings_local = repo / ".claude" / "settings.local.json"
    settings_local.write_text(json.dumps({"enabledPlugins": {"orig@mp": True}}))

    psl.backup_settings_local_shared(settings_local, "A", os.getpid())
    psl.backup_settings_local_shared(settings_local, "B", os.getpid())
    settings_local.write_text(
        json.dumps({"enabledPlugins": {"orig@mp": True, "cwd-written@mp": True}})
    )

    psl.restore_settings_local_shared(
        settings_local, "B"
    )  # non-LIFO : dernière ouverte ferme en 2ᵉ
    assert (
        json.loads(settings_local.read_text())["enabledPlugins"]["cwd-written@mp"]
        is True
    )
    psl.restore_settings_local_shared(settings_local, "A")
    assert json.loads(settings_local.read_text()) == {
        "enabledPlugins": {"orig@mp": True}
    }


def test_shared_backup_crashed_pid_is_purged_and_restore_still_fires(
    monkeypatch, tmp_path
):
    _use_state_dir(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings_local = repo / ".claude" / "settings.local.json"
    settings_local.write_text(json.dumps({"enabledPlugins": {"orig@mp": True}}))

    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"]
    )  # portable, pas de "true" sous Windows
    dead_pid = proc.pid
    proc.wait()  # garanti mort : le fd n'a jamais été relâché explicitement, juste fermé

    psl.backup_settings_local_shared(settings_local, "crashed", dead_pid)
    psl.backup_settings_local_shared(settings_local, "alive", os.getpid())
    settings_local.write_text(
        json.dumps({"enabledPlugins": {"orig@mp": True, "cwd-written@mp": True}})
    )

    psl.restore_settings_local_shared(settings_local, "alive")
    assert json.loads(settings_local.read_text()) == {
        "enabledPlugins": {"orig@mp": True}
    }


def test_shared_backup_never_existed_is_removed_on_full_restore(monkeypatch, tmp_path):
    _use_state_dir(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    settings_local = repo / ".claude" / "settings.local.json"

    psl.backup_settings_local_shared(settings_local, "A", os.getpid())
    settings_local.write_text(json.dumps({"enabledPlugins": {"cwd-written@mp": True}}))
    psl.restore_settings_local_shared(settings_local, "A")
    assert not settings_local.exists()


class _FakeKernel32:
    """Boundary fake for `ctypes.windll.kernel32` — same posture as faking
    `subprocess.run` for the `claude` CLI elsewhere in this file."""

    def __init__(self, *, handle: int, exit_code: int | None):
        self._handle = handle
        self._exit_code = exit_code
        self.closed_handles: list[int] = []

    def OpenProcess(self, access, inherit, pid):
        return self._handle

    def GetExitCodeProcess(self, handle, exit_code_ptr):
        if self._exit_code is None:
            return 0  # échec de l'appel
        exit_code_ptr.contents.value = self._exit_code
        return 1

    def CloseHandle(self, handle):
        self.closed_handles.append(handle)
        return 1


def _patch_windll(monkeypatch, kernel32: _FakeKernel32) -> None:
    import ctypes

    monkeypatch.setattr(psl.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "windll", type("W", (), {"kernel32": kernel32})(), raising=False
    )


def test_is_alive_windows_still_active_is_true(monkeypatch):
    kernel32 = _FakeKernel32(handle=1, exit_code=259)  # STILL_ACTIVE
    _patch_windll(monkeypatch, kernel32)
    assert psl._is_alive(1234) is True
    assert kernel32.closed_handles == [1]


def test_is_alive_windows_exited_process_is_false(monkeypatch):
    kernel32 = _FakeKernel32(handle=1, exit_code=0)  # sorti, pas STILL_ACTIVE
    _patch_windll(monkeypatch, kernel32)
    assert psl._is_alive(1234) is False


def test_is_alive_windows_missing_pid_is_false(monkeypatch):
    kernel32 = _FakeKernel32(
        handle=0, exit_code=None
    )  # OpenProcess échoue (handle nul)
    _patch_windll(monkeypatch, kernel32)
    assert psl._is_alive(9999) is False
    assert kernel32.closed_handles == []  # jamais fermé un handle nul
