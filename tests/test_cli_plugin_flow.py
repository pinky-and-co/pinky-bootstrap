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
from setup import cli, plugin_install, plugin_reconcile, state_file


class _ClaudeCliSim:
    """Reproduces the measured on-disk effect of `claude plugin install/uninstall`."""

    def __init__(self, fake_home: Path):
        self.fake_home = fake_home
        self.calls: list[tuple[list[str], Path | None]] = []
        # plugin id -> plugins `claude plugin install` also installs at the same scope
        self.dependencies: dict[str, list[str]] = {}
        # dependencies `claude plugin install` brought along, by scope root — what `prune` may drop
        self.auto_installed: dict[Path, set[str]] = {}

    def __call__(self, cmd, **kw):
        cwd = Path(kw["cwd"]) if kw.get("cwd") else None
        self.calls.append((list(cmd), cwd))
        if cmd[:3] == ["claude", "plugin", "install"]:
            scope = cmd[cmd.index("--scope") + 1]
            self._toggle(self._root(scope, cwd), cmd[3], on=True)
            root = self._root(scope, cwd)
            for dependency in self.dependencies.get(cmd[3].split("@", 1)[0], []):
                # a plugin already installed on its own is not "auto-installed": prune keeps it
                if not self._enabled(root, dependency):
                    self.auto_installed.setdefault(root, set()).add(dependency)
                self._toggle(root, dependency, on=True)
        elif cmd[:3] == ["claude", "plugin", "prune"]:
            self._prune(self._root(cmd[cmd.index("--scope") + 1], cwd))
        elif cmd[:3] == ["claude", "plugin", "uninstall"]:
            scope = cmd[cmd.index("--scope") + 1]
            self._toggle(self._root(scope, cwd), cmd[3], on=False)
        return subprocess.CompletedProcess(cmd, 0)

    @staticmethod
    def _enabled(root: Path, spec: str) -> bool:
        settings = root / ".claude" / "settings.json"
        if not settings.is_file():
            return False
        return (
            json.loads(settings.read_text()).get("enabledPlugins", {}).get(spec) is True
        )

    def _prune(self, root: Path) -> None:
        """Drop an auto-installed dependency once no enabled plugin at that scope needs it."""
        settings = root / ".claude" / "settings.json"
        enabled = json.loads(settings.read_text()).get("enabledPlugins", {})
        needed = {
            dep
            for spec in enabled
            for dep in self.dependencies.get(spec.split("@", 1)[0], [])
        }
        for dependency in self.auto_installed.get(root, set()) - needed:
            self._toggle(root, dependency, on=False)

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

    monkeypatch.setattr(plugin_reconcile, "_USER_CLAUDE", home / ".claude")
    monkeypatch.setattr(
        plugin_reconcile,
        "_REGISTRY",
        home / ".claude" / "plugins" / "installed_plugins.json",
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    monkeypatch.setattr(plugin_install, "_CACHE_ROOT", tmp_path / "cache")
    plugin_dir = tmp_path / "cache" / "mp" / "pc-snow" / "0.1.0"
    (plugin_dir / "skills").mkdir(parents=True)
    monkeypatch.setattr(
        plugin_install, "resolve_install_path", lambda *a, **k: plugin_dir
    )
    sim = _ClaudeCliSim(home)
    monkeypatch.setattr(subprocess, "run", sim)
    ws = tmp_path / "workspace"
    (ws / "pinky-core" / ".git").mkdir(parents=True)
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


def _enabled_at(settings_dir: Path, spec: str) -> object:
    """`enabledPlugins[spec]` in `<settings_dir>/.claude/settings.json`, or KeyError-safe `None`."""
    p = settings_dir / ".claude" / "settings.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text()).get("enabledPlugins", {}).get(spec)


def _write_enable(settings_dir: Path, spec: str, value: bool) -> None:
    p = settings_dir / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(p.read_text()) if p.is_file() else {}
    data.setdefault("enabledPlugins", {})[spec] = value
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_project_scope_keeps_a_pre_existing_global_enable_when_the_removal_is_declined(
    env, monkeypatch
):
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    _canned_input(monkeypatch, ["p", "2", "0", "n"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True
    assert not _uninstalled(env.sim)


def test_wizard_refusal_leaves_a_pre_existing_global_enable_alone(env, monkeypatch):
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    _canned_input(monkeypatch, ["p", "2", "99"])

    with pytest.raises(SystemExit):
        cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True


def test_user_scope_keeps_the_enable_and_writes_no_project_settings(env, monkeypatch):
    _canned_input(monkeypatch, ["u"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True
    assert not (env.ws / "pinky-core" / ".claude" / "settings.json").exists()
    assert not _uninstalled(env.sim)


def test_keep_user_scope_plugin_stays_at_user_and_skips_the_wizard(env, monkeypatch):
    monkeypatch.setattr(plugin_install, "KEEP_USER_SCOPE", frozenset({"pc-snow"}))
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("the wizard must not run")
    )

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is True
    assert not (env.ws / "pinky-core" / ".claude" / "settings.json").exists()
    assert not _uninstalled(env.sim)


def test_pc_autodiscovery_is_declared_keep_user_scope():
    assert "pc-autodiscovery" in plugin_install.KEEP_USER_SCOPE


def test_pc_statusline_is_declared_keep_user_scope():
    """`pc-statusline` and `pc-autodiscovery` are placed at user scope with no scope question."""
    assert "pc-statusline" in plugin_install.KEEP_USER_SCOPE


def test_rescope_removes_a_stale_enable_after_a_confirmed_prompt(env, monkeypatch):
    _write_enable(env.ws, "pc-snow", True)
    _canned_input(monkeypatch, ["p", "2", "0", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True
    assert _enabled_at(env.ws, "pc-snow") is None


def test_rescope_asks_first_and_a_no_keeps_the_stale_scope(env, monkeypatch, capsys):
    _write_enable(env.ws, "pc-snow", True)
    _canned_input(monkeypatch, ["p", "2", "0", "n"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws, "pc-snow") is True
    assert "left unchanged at: ." in capsys.readouterr().out


def test_rescope_prompt_defaults_to_keeping_the_old_scope(env, monkeypatch):
    """Enter alone at "Also remove … ? [y/N]" keeps the scope the plugin was already enabled at."""
    _write_enable(env.ws, "pc-snow", True)
    _canned_input(monkeypatch, ["p", "2", "0", ""])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws, "pc-snow") is True
    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True


def test_rescope_yes_flag_skips_the_prompt(env, monkeypatch):
    _write_enable(env.ws, "pc-snow", True)
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow", "--yes"])

    assert _enabled_at(env.ws, "pc-snow") is None


def test_rescope_leaves_a_deliberate_disabled_opt_out_alone(env, monkeypatch):
    """A `false` key is an explicit "parent wins, off here" — an install adds a scope, it must
    not silently undo the opt-out."""
    _write_enable(env.ws, "pc-snow", False)
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws, "pc-snow") is False


def test_a_leftover_user_enable_is_offered_for_removal_and_removed_on_yes(
    env, monkeypatch
):
    """Only `pc-statusline` and `pc-autodiscovery` belong at user scope. Any other plugin found
    there is a leftover (an interrupted run, a dependency) — it used to be trusted as deliberate
    because it predated the command, so every later run kept it."""
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    _canned_input(monkeypatch, ["p", "2", "0", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is False
    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True


def test_a_leftover_user_enable_is_removed_without_asking_under_yes(env, monkeypatch):
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow", "--yes"])

    assert _user_enabled(env.home, "pc-snow") is False


def test_force_busts_the_cache_dir_before_fetching(env, monkeypatch, capsys):

    install = plugin_install.resolve_install_path("pc-snow")
    assert install.exists()
    _canned_input(monkeypatch, ["u"])

    cli.main(["--plugin", "pc-snow", "--marketplace", "mp", "--force"])

    assert not install.exists()
    assert "cache cleared for pc-snow@mp" in capsys.readouterr().out


def test_rescope_without_marketplace_finds_the_scopes_recorded_under_the_full_key(
    env, monkeypatch
):
    """`--plugin pc-snow` names no marketplace, but the settings key is `pc-snow@mp`: the old
    scope must still be found and offered for removal."""
    _write_enable(env.ws, "pc-snow@mp", True)
    _canned_input(monkeypatch, ["p", "2", "0", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws / "pinky-core", "pc-snow@mp") is True
    assert _enabled_at(env.ws, "pc-snow@mp") is None


def test_rescope_without_marketplace_asks_which_one_when_two_carry_the_plugin(
    env, monkeypatch, capsys
):
    _write_enable(env.ws, "pc-snow@mp1", True)
    _write_enable(env.ws / "pinky-core", "pc-snow@mp2", True)
    # marketplace choice "1" (mp2), then scope p / depth 2 / target 0, then no to the purge
    _canned_input(monkeypatch, ["1", "p", "2", "0", "n"])

    cli.main(["--plugin", "pc-snow"])

    out = capsys.readouterr().out
    assert "0) mp1" in out and "1) mp2" in out
    assert _enabled_at(env.ws / "pinky-core", "pc-snow@mp2") is True


def test_a_leftover_user_enable_takes_its_unneeded_dependencies_with_it(
    env, monkeypatch
):
    """`pc-git` left at user scope also left `pc-core` there as its dependency. Removing the
    leftover must not leave the dependency stranded — `claude plugin prune` is the official way."""
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    env.sim(["claude", "plugin", "install", "pc-snow", "--scope", "user"])
    assert _user_enabled(env.home, "pc-core") is True
    _canned_input(monkeypatch, ["p", "2", "0", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_enabled(env.home, "pc-snow") is False
    assert _user_enabled(env.home, "pc-core") is False


def _user_installs(sim: _ClaudeCliSim) -> list[list[str]]:
    return [
        c
        for c, _ in sim.calls
        if c[:3] == ["claude", "plugin", "install"]
        and c[c.index("--scope") + 1] == "user"
    ]


def test_project_scope_never_installs_at_user_scope(env, monkeypatch):
    """Nothing is downloaded before the scope is chosen, and a project choice downloads straight
    at the project: user scope is not a step on the way (measured 2026-09-02 and 2026-09-19)."""
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_installs(env.sim) == []
    assert _user_enabled(env.home, "pc-snow") is False
    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True


def test_a_dependency_lands_at_the_chosen_project_never_at_user_scope(env, monkeypatch):
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    _canned_input(monkeypatch, ["p", "2", "0"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws / "pinky-core", "pc-core") is True
    assert _user_enabled(env.home, "pc-core") is False


def test_a_refused_wizard_installs_nothing(env, monkeypatch):
    """The wizard asks the scope before anything is downloaded, so a refusal leaves nothing."""
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    _canned_input(monkeypatch, ["garbage"])

    with pytest.raises(SystemExit):
        cli.main(["--plugin", "pc-snow"])

    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []


def test_an_interrupted_wizard_installs_nothing(env, monkeypatch):
    def interrupt(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)

    with pytest.raises(KeyboardInterrupt):
        cli.main(["--plugin", "pc-snow"])

    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []


def test_choosing_user_scope_installs_there(env, monkeypatch):
    _canned_input(monkeypatch, ["u"])

    cli.main(["--plugin", "pc-snow"])

    assert len(_user_installs(env.sim)) == 1
    assert _user_enabled(env.home, "pc-snow") is True
