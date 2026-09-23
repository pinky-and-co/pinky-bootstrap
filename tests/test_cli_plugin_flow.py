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
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli, plugin_curated, plugin_install, plugin_reconcile, state_file
from setup.common import WorkspaceOrigin
from setup.plugin_curated import CuratedEntry


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
    monkeypatch.setattr(
        cli, "resolve_workspace_root", lambda *a, **k: WorkspaceOrigin(ws, "test")
    )
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


# ── cli.py dispatch: the Workspace line, `--workspace` honored ──


def test_install_prints_the_workspace_line_first(env, monkeypatch, capsys):
    from setup.common import resolve_workspace_root as real_resolve_workspace_root

    monkeypatch.setattr(cli, "resolve_workspace_root", real_resolve_workspace_root)
    _canned_input(monkeypatch, ["0", "y"])

    cli.main(["--plugin", "pc-snow", "--workspace", str(env.ws)])

    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line == f"Workspace: {env.ws.resolve()} (via --workspace)"


def test_user_scope_keeps_the_enable_and_writes_no_project_settings(env, monkeypatch):
    _canned_input(monkeypatch, ["0", "y"])

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


def test_dry_run_with_force_writes_and_deletes_nothing(env, monkeypatch):
    """NFR-0024-31: `--dry-run` writes nothing — not even the `--force` cache-bust, which is
    destructive on its own regardless of what the table decides."""
    plugin_dir = plugin_install.resolve_install_path("pc-snow")
    assert plugin_dir.exists()
    settings = env.home / ".claude" / "settings.json"
    before = settings.read_text() if settings.exists() else None
    _canned_input(monkeypatch, [""])  # keep the table as shown

    cli.main(["--plugin", "pc-snow", "--force", "--dry-run"])

    assert plugin_dir.exists()
    after = settings.read_text() if settings.exists() else None
    assert after == before
    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []


def test_a_declined_plan_writes_nothing(env, monkeypatch):
    settings = env.home / ".claude" / "settings.json"
    before = settings.read_text() if settings.exists() else None
    _canned_input(monkeypatch, ["0", "n"])

    cli.main(["--plugin", "pc-snow"])

    after = settings.read_text() if settings.exists() else None
    assert after == before
    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []


def test_rescope_leaves_a_deliberate_disabled_opt_out_alone(env, monkeypatch):
    """A `false` key is an explicit "parent wins, off here" — the table only ever adds a target
    the person checks (row 2, pinky-core), it never surfaces a disabled row (row 1, the
    workspace root) as something to re-enable."""
    _write_enable(env.ws, "pc-snow", False)
    _canned_input(monkeypatch, ["2", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws, "pc-snow") is False


def test_force_busts_the_cache_dir_before_fetching(env, monkeypatch, capsys):

    install = plugin_install.resolve_install_path("pc-snow")
    assert install.exists()
    _canned_input(monkeypatch, ["0", "y"])

    cli.main(["--plugin", "pc-snow", "--marketplace", "mp", "--force"])

    assert not install.exists()
    assert "cache cleared for pc-snow@mp" in capsys.readouterr().out


def _user_installs(sim: _ClaudeCliSim) -> list[list[str]]:
    return [
        c
        for c, _ in sim.calls
        if c[:3] == ["claude", "plugin", "install"]
        and c[c.index("--scope") + 1] == "user"
    ]


def test_project_scope_never_installs_at_user_scope(env, monkeypatch):
    """Nothing is downloaded before the table is confirmed, and a project target downloads
    straight there: user scope is not a step on the way (measured 2026-09-02 and 2026-09-19,
    still true once `install` delegates to the same `enable` flow, FR-0024-31)."""
    _canned_input(monkeypatch, ["2", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_installs(env.sim) == []
    assert _user_enabled(env.home, "pc-snow") is False
    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True


def test_a_dependency_lands_at_the_chosen_project_never_at_user_scope(env, monkeypatch):
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    _canned_input(monkeypatch, ["2", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws / "pinky-core", "pc-core") is True
    assert _user_enabled(env.home, "pc-core") is False


def test_a_refused_wizard_installs_nothing(env, monkeypatch):
    """An invalid table answer aborts before anything is downloaded, and leaves a pre-existing
    global enable untouched."""
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    _canned_input(monkeypatch, ["garbage"])

    with pytest.raises(SystemExit):
        cli.main(["--plugin", "pc-snow"])

    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []
    assert _user_enabled(env.home, "pc-snow") is True


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
    _canned_input(monkeypatch, ["0", "y"])

    cli.main(["--plugin", "pc-snow"])

    assert len(_user_installs(env.sim)) == 1
    assert _user_enabled(env.home, "pc-snow") is True


def test_a_second_install_with_nothing_to_do_still_rewires_the_status_line(
    env, tmp_path, monkeypatch
):
    """A re-run after `claude plugin update` must still refresh a stale statusLine path even when
    the table shows the plugin already exactly where it should be — "nothing to do" is not
    "nothing installed"."""
    plugin_dir = tmp_path / "cache" / "mp" / "pc-snow" / "0.1.0"
    (plugin_dir / "scripts").mkdir(parents=True)
    (plugin_dir / "scripts" / "statusline.py").write_text("", encoding="utf-8")
    _canned_input(monkeypatch, ["0", "y"])
    cli.main(["--plugin", "pc-snow"])
    (env.home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    _canned_input(monkeypatch, [""])  # keep the table as shown → "nothing to do"
    cli.main(["--plugin", "pc-snow"])

    settings = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert settings["statusLine"] == {
        "type": "command",
        "command": f'python3 "{plugin_dir / "scripts" / "statusline.py"}"',
    }


# ── no name: the curated/installed picker (install/enable), "all installed" (disable) ──────


def test_install_with_no_name_opens_the_picker(env, monkeypatch):
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    # picker: keep pc-snow checked (FR-0024-37 prechecks it, nothing installed yet); then row 0
    # (user) in the target table; confirm.
    _canned_input(monkeypatch, ["", "0", "y"])

    cli.main(["--plugin"])

    assert _user_enabled(env.home, "pc-snow") is True


def test_install_on_a_fresh_machine_adds_the_unregistered_marketplace_then_installs(
    env, monkeypatch
):
    """FR-0024-37/39/43: a curated marketplace nothing has ever `marketplace add`ed still shows
    up (as one row), gets added on confirmation, expands, and gets remembered in the user file."""
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("fresh", "owner/fresh-plugins")],
    )
    marketplace_calls = []

    def fake_add(entry, workspace_root):
        marketplace_calls.append(entry.marketplace)
        monkeypatch.setattr(
            plugin_curated, "expand_entry", lambda e: ["pc-fresh"] if e is entry else []
        )

    monkeypatch.setattr(plugin_curated, "add_marketplace", fake_add)
    user_file = env.ws.parent / "user-curated.toml"
    # picker: keep the one row checked (FR-0024-37); confirm the marketplace add; confirm saving
    # it to the user file; row 0 (user) in the target table; confirm.
    _canned_input(monkeypatch, ["", "y", "y", "0", "y"])

    cli.main(["--plugin", "--list", str(user_file)])

    assert marketplace_calls == ["fresh"]
    assert _user_enabled(env.home, "pc-fresh") is True
    assert tomllib.loads(user_file.read_text()) == {
        "entries": [{"marketplace": "fresh", "source": "owner/fresh-plugins"}]
    }


def test_enable_with_no_name_opens_the_picker(env, monkeypatch):
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    _canned_input(monkeypatch, ["", "0", "y"])

    cli.main(["--plugin-enable"])

    assert _user_enabled(env.home, "pc-snow") is True


def test_disable_with_no_name_acts_on_every_installed_plugin_without_asking_which(
    env, monkeypatch
):
    """FR-0024-34: no name → every installed plugin's current enables, via the compact
    (checked-only) table — one row here, not the full plugin x every-known-target grid."""
    _write_enable(env.ws, "pc-snow", True)
    _canned_input(
        monkeypatch, ["0", "y"]
    )  # the table's own toggle+confirm, not a name picker

    cli.main(["--plugin-disable"])

    assert _enabled_at(env.ws, "pc-snow") is None


def test_disable_with_no_name_and_nothing_installed_is_a_clean_no_op(env, capsys):
    cli.main(["--plugin-disable"])

    assert "no plugin installed" in capsys.readouterr().out
    assert env.sim.calls == []


def test_disable_with_no_name_shows_the_compact_table_not_the_full_grid(
    env, monkeypatch, capsys
):
    """A plugin enabled at only one target must not drag every known target (workspace root,
    every group, every repo) into the "no name" table — only rows actually checked."""
    _write_enable(env.ws, "pc-snow", True)
    _write_enable(env.ws / "pinky-core", "pc-x", True)
    _canned_input(monkeypatch, ["0 1", "y"])

    cli.main(["--plugin-disable"])

    table = capsys.readouterr().out
    assert table.count(") [") == 2
    assert _enabled_at(env.ws, "pc-snow") is None
    assert _enabled_at(env.ws / "pinky-core", "pc-x") is None
