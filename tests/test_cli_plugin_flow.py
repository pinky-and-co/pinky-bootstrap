"""`setup.cli.main(["--plugin", …])` — the orchestration around the scope wizard.

The caller owns the user-scope lifecycle: `install_plugin_files` enables the plugin at user scope
just to fetch + inspect it, and `main` must drop that enable once real project targets are placed
— or on a wizard refusal — but never when the plugin was a legitimate global enable to begin with
(every `pc-*` plugin is user-enabled on the author's machine right now).

Boundary fakes only: `subprocess.run` (the `claude` CLI), the home-dir paths the modules read,
and `resolve_install_path` (a registry read the sim does not populate). `main` and
`run_marketplace_wizard` stay real.
"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli, plugin_install, state_file


class _ClaudeCliSim:
    """Reproduces the measured on-disk effect of `claude plugin install/uninstall` (2026-09-02)."""

    def __init__(self, fake_home: Path):
        self.fake_home = fake_home
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd, **kw):
        cwd = Path(kw["cwd"]) if kw.get("cwd") else None
        self.calls.append((list(cmd), cwd))
        if cmd[:3] == ["claude", "plugin", "install"]:
            scope = cmd[cmd.index("--scope") + 1]
            self._toggle(self._root(scope, cwd), cmd[3], on=True)
        elif cmd[:3] == ["claude", "plugin", "uninstall"]:
            scope = cmd[cmd.index("--scope") + 1]
            self._toggle(self._root(scope, cwd), cmd[3], on=False)
        return subprocess.CompletedProcess(cmd, 0)

    def _root(self, scope: str, cwd: Path | None) -> Path:
        return self.fake_home if scope == "user" else cwd

    @staticmethod
    def _toggle(root: Path, spec: str, *, on: bool) -> None:
        settings = root / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(settings.read_text()) if settings.is_file() else {}
        enabled = data.setdefault("enabledPlugins", {})
        if on:
            enabled[spec] = True
        else:
            enabled.pop(spec, None)
        settings.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        plugin_install, "_USER_SETTINGS", home / ".claude" / "settings.json"
    )
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    # the fetched plugin ships no status line -> the flow proceeds to the wizard
    plugin_dir = tmp_path / "cache" / "pc-snow"
    (plugin_dir / "skills").mkdir(parents=True)
    monkeypatch.setattr(
        plugin_install, "resolve_install_path", lambda *a, **k: plugin_dir
    )
    sim = _ClaudeCliSim(home)
    monkeypatch.setattr(subprocess, "run", sim)
    ws = tmp_path / "workspace"
    (ws / "pinky-core" / ".git").mkdir(
        parents=True
    )  # one pickable depth-2 target (a repo)
    monkeypatch.setattr(cli, "WORKSPACE_ROOT", ws)
    return SimpleNamespace(sim=sim, home=home, ws=ws)


def _user_enabled(home: Path, spec: str) -> bool:
    p = home / ".claude" / "settings.json"
    if not p.is_file():
        return False
    return json.loads(p.read_text()).get("enabledPlugins", {}).get(spec) is True


def _canned_input(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _uninstalled(sim: _ClaudeCliSim) -> bool:
    return any(c[:3] == ["claude", "plugin", "uninstall"] for c, _ in sim.calls)


# ── project scope, plugin not previously user-enabled ──────────────────────


def test_project_scope_drops_the_fetch_time_user_enable(env, monkeypatch):
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is False  # transient enable cleaned up
    assert json.loads(
        (env.ws / "pinky-core" / ".claude" / "settings.json").read_text()
    )["enabledPlugins"] == {"pc-snow": True}
    assert env.sim.calls[-1] == (
        ["claude", "plugin", "uninstall", "pc-snow", "--scope", "user", "--yes"],
        None,
    )


# ── project scope, plugin ALREADY user-enabled (must not be stripped) ──────


def test_project_scope_preserves_a_pre_existing_global_enable(env, monkeypatch):
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)  # predates the command
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True  # untouched
    assert not _uninstalled(env.sim)


# ── wizard refusal paths ──────────────────────────────────────────────────


def test_wizard_refusal_undoes_the_fetch_time_enable(env, monkeypatch):
    _canned_input(monkeypatch, ["garbage"])  # unknown scope -> SystemExit

    with pytest.raises(SystemExit):
        cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is False  # not left globally enabled


def test_wizard_refusal_leaves_a_pre_existing_global_enable_alone(env, monkeypatch):
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    _canned_input(monkeypatch, ["p", "2", "99"])  # out-of-range -> SystemExit

    with pytest.raises(SystemExit):
        cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True  # not stripped by the cleanup


# ── user scope chosen ─────────────────────────────────────────────────────


def test_user_scope_keeps_the_enable_and_writes_no_project_settings(env, monkeypatch):
    _canned_input(monkeypatch, ["u"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True
    assert not (env.ws / "pinky-core" / ".claude" / "settings.json").exists()
    assert not _uninstalled(env.sim)
