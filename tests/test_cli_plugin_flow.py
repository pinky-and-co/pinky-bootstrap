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
from setup import cli, plugin_curated, plugin_install, plugin_reconcile, state_file, tui
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
    # `plugin_catalog.CLAUDE_DIR` is bound at import time, so the `Path.home` patch misses it:
    # without this, the real machine's registered marketplaces would be read.
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(plugin_curated.plugin_catalog, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    monkeypatch.setattr(plugin_install, "_CACHE_ROOT", tmp_path / "cache")
    # `force_refetch` lit ce registre pour savoir quoi supprimer : le vrai pointerait sur le vrai cache.
    monkeypatch.setattr(
        plugin_install,
        "_REGISTRY",
        home / ".claude" / "plugins" / "installed_plugins.json",
    )
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


def _stub_picker(monkeypatch, fake):
    """Replaces the interactive checkbox screen (`tui.run_checklist`) with `fake(items, title, **kw)` — every
    `[y/N]` confirmation after it still goes through the real `input()`, via `_canned_input`."""
    monkeypatch.setattr(tui, "run_checklist", fake)


def _keep_as_shown(items, title, **kwargs):
    return [item.checked for item in items]


def _uncheck_all(items, title, **kwargs):
    return [False for _ in items]


def _pick_and_target(target_text):
    """A fake covering both checkbox screens the "no name" flow can open in one run: the plugin-name
    picker (title starts with "pick plugin") is kept exactly as shown, the plugin x target table
    gets `target_text` checked on top of whatever was already checked."""

    def fake(items, title, **kwargs):
        if title.startswith("pick plugin"):
            return [item.checked for item in items]
        return [item.checked or item.text == target_text for item in items]

    return fake


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


# ── dispatch: the Workspace line, `--workspace` honored ──


def test_install_prints_the_workspace_line_first(env, monkeypatch, capsys):
    from setup.common import resolve_workspace_root as real_resolve_workspace_root

    monkeypatch.setattr(cli, "resolve_workspace_root", real_resolve_workspace_root)
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin", "pc-snow", "--workspace", str(env.ws)])

    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line == f"Workspace: {env.ws.resolve()} (via --workspace)"


def test_user_scope_keeps_the_enable_and_writes_no_project_settings(env, monkeypatch):
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

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
    """`--dry-run` writes nothing — not even the `--force` cache-bust, which is
    destructive on its own regardless of what the table decides."""
    plugin_dir = plugin_install.resolve_install_path("pc-snow")
    assert plugin_dir.exists()
    settings = env.home / ".claude" / "settings.json"
    before = settings.read_text() if settings.exists() else None
    _stub_picker(monkeypatch, _keep_as_shown)

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
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["n"])

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
    _stub_picker(monkeypatch, _pick_and_target("pinky-core"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws, "pc-snow") is False


def test_force_busts_the_cache_dir_and_refetches_it(env, monkeypatch, capsys):
    install = plugin_install.resolve_install_path("pc-snow")
    assert install.exists()
    registry = env.home / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "pc-snow@mp": [
                        {
                            "scope": "user",
                            "installPath": str(install),
                            "version": "0.1.0",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin", "pc-snow", "--marketplace", "mp", "--force"])

    assert not install.exists()
    assert "cache cleared for pc-snow@mp" in capsys.readouterr().out
    assert _user_installs(env.sim)[0] == [
        "claude",
        "plugin",
        "install",
        "pc-snow@mp",
        "--scope",
        "user",
        "--yes",
    ]


def _user_installs(sim: _ClaudeCliSim) -> list[list[str]]:
    return [
        c
        for c, _ in sim.calls
        if c[:3] == ["claude", "plugin", "install"]
        and c[c.index("--scope") + 1] == "user"
    ]


def test_project_scope_never_installs_at_user_scope(env, monkeypatch):
    """Nothing is downloaded before the table is confirmed, and a project target downloads
    straight there: user scope is not a step on the way."""
    _stub_picker(monkeypatch, _pick_and_target("pinky-core"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin", "pc-snow"])

    assert _user_installs(env.sim) == []
    assert _user_enabled(env.home, "pc-snow") is False
    assert _enabled_at(env.ws / "pinky-core", "pc-snow") is True


def test_a_dependency_lands_at_the_chosen_project_never_at_user_scope(env, monkeypatch):
    env.sim.dependencies = {"pc-snow": ["pc-core"]}
    _stub_picker(monkeypatch, _pick_and_target("pinky-core"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin", "pc-snow"])

    assert _enabled_at(env.ws / "pinky-core", "pc-core") is True
    assert _user_enabled(env.home, "pc-core") is False


def test_a_cancelled_wizard_installs_nothing(env, monkeypatch):
    """Ctrl-C on the checkbox screen propagates as `KeyboardInterrupt` (turned into exit 130 by
    `cli_pinky`) before anything is downloaded, and leaves a pre-existing global
    enable untouched."""
    _ClaudeCliSim._toggle(env.home, "pc-snow", on=True)
    env.sim.dependencies = {"pc-snow": ["pc-core"]}

    def interrupted(items, title, **kwargs):
        raise KeyboardInterrupt

    _stub_picker(monkeypatch, interrupted)

    with pytest.raises(KeyboardInterrupt):
        cli.main(["--plugin", "pc-snow"])

    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []
    assert _user_enabled(env.home, "pc-snow") is True


def test_an_interrupted_wizard_installs_nothing(env, monkeypatch):
    def interrupt(items, title, **kw):
        raise KeyboardInterrupt

    _stub_picker(monkeypatch, interrupt)

    with pytest.raises(KeyboardInterrupt):
        cli.main(["--plugin", "pc-snow"])

    assert [
        c for c, _ in env.sim.calls if c[:3] == ["claude", "plugin", "install"]
    ] == []


def test_choosing_user_scope_installs_there(env, monkeypatch):
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

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
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])
    cli.main(["--plugin", "pc-snow"])
    (env.home / ".claude" / "settings.json").write_text("{}", encoding="utf-8")

    _stub_picker(
        monkeypatch, _keep_as_shown
    )  # keep the table as shown → "nothing to do"
    cli.main(["--plugin", "pc-snow"])

    settings = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert settings["statusLine"] == {
        "type": "command",
        "command": f'python3 "{plugin_dir / "scripts" / "statusline.py"}"',
    }


# ── no name: the curated/installed picker (install/enable), "all installed" (disable) ──────


def test_install_with_no_name_opens_the_picker(env, monkeypatch):
    (env.home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": "/wherever"}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    # picker: keep pc-snow checked (nothing installed yet, so it is prechecked); then "user"
    # checked in the target table; confirm.
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin"])

    assert _user_enabled(env.home, "pc-snow@mp") is True


def test_install_with_no_name_skips_the_table_for_an_already_installed_pick(
    env, monkeypatch
):
    """The table covers what was *newly* selected. Keeping an already-installed
    plugin checked in the "no name" picker must not reopen its own plugin x every-known-target
    table — that was the original 528-row bug, reachable again through this path if unfiltered."""
    _write_enable(env.ws, "pc-snow", True)
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    _stub_picker(
        monkeypatch, _keep_as_shown
    )  # picker only — no further prompt ever asked
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("no confirmation should ever be asked")
    )

    cli.main(["--plugin"])

    out = env.sim.calls
    assert out == []


def test_enable_with_no_name_and_nothing_new_selected_says_so_and_exits_cleanly(
    env, monkeypatch, capsys
):
    _write_enable(env.ws, "pc-snow", True)
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    _stub_picker(monkeypatch, _keep_as_shown)

    cli.main(["--plugin-enable"])

    assert "nothing selected" in capsys.readouterr().out


def test_install_on_a_fresh_machine_adds_the_unregistered_marketplace_then_installs(
    env, monkeypatch
):
    """A curated marketplace nothing has ever `marketplace add`ed still shows
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
    # picker: keep the one row checked; confirm the marketplace add; confirm saving
    # it to the user file; "user" checked in the target table; confirm.
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y", "y", "y"])

    cli.main(["--plugin", "--list", str(user_file)])

    assert marketplace_calls == ["fresh"]
    assert _user_enabled(env.home, "pc-fresh") is True
    assert tomllib.loads(user_file.read_text()) == {
        "entries": [{"marketplace": "fresh", "source": "owner/fresh-plugins"}]
    }


def test_enable_with_no_name_opens_the_picker(env, monkeypatch):
    (env.home / ".claude" / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"mp": {"installLocation": "/wherever"}}), encoding="utf-8"
    )
    monkeypatch.setattr(
        plugin_curated,
        "load_curated_entries",
        lambda *a, **k: [CuratedEntry("mp", "owner/repo", plugin="pc-snow")],
    )
    _stub_picker(monkeypatch, _pick_and_target("user"))
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin-enable"])

    assert _user_enabled(env.home, "pc-snow@mp") is True


def test_disable_with_no_name_acts_on_every_installed_plugin_without_asking_which(
    env, monkeypatch
):
    """No name → every installed plugin's current enables, via the compact
    (checked-only) table — one row here, not the full plugin x every-known-target grid."""
    _write_enable(env.ws, "pc-snow", True)
    _stub_picker(
        monkeypatch, _uncheck_all
    )  # the table's own toggle+confirm, not a name picker
    _canned_input(monkeypatch, ["y"])

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
    seen_items = []

    def uncheck_and_record(items, title, **kwargs):
        seen_items.extend(items)
        return _uncheck_all(items, title, **kwargs)

    _stub_picker(monkeypatch, uncheck_and_record)
    _canned_input(monkeypatch, ["y"])

    cli.main(["--plugin-disable"])

    assert len([it for it in seen_items if it.selectable]) == 2
    assert _enabled_at(env.ws, "pc-snow") is None
    assert _enabled_at(env.ws / "pinky-core", "pc-x") is None
