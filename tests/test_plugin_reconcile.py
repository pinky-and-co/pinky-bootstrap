"""`setup/plugin_reconcile.py::audit_plugins` — the state reader behind `pinky plugins reconcile`.

No mocks: `audit_plugins` only reads files. The fixture builds a fake `~/.claude` and a fake
workspace tree on `tmp_path` and points the module's two roots at them.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_reconcile, state_file
from setup.plugin_reconcile import apply_reconcile, audit_plugins, print_audit_report


@pytest.fixture
def world(tmp_path, monkeypatch):
    user_claude = tmp_path / "home" / ".claude"
    (user_claude / "plugins").mkdir(parents=True)
    monkeypatch.setattr(plugin_reconcile, "_USER_CLAUDE", user_claude)
    monkeypatch.setattr(
        plugin_reconcile,
        "_REGISTRY",
        user_claude / "plugins" / "installed_plugins.json",
    )
    ws = tmp_path / "workspace"
    # a group with two nested repos + a repo directly at depth 1
    for rel in (
        "bootstrap/pinky-bootstrap",
        "pinky-lib/pinky-core",
        "pinky-lib/pinky-snowpark",
    ):
        (ws / rel / ".git").mkdir(parents=True)
    return user_claude, ws


def _write_enabled(settings_file: Path, mapping: dict) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({"enabledPlugins": mapping}), encoding="utf-8")


def _write_registry(user_claude: Path, plugins: dict) -> None:
    (user_claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8"
    )


# ── the union of both registries (FR-0023-33) ──────────────────────────────


def test_audit_unions_every_source(world):
    user_claude, ws = world
    _write_enabled(user_claude / "settings.json", {"kept@mp": True, "off@mp": False})
    _write_enabled(ws / "pinky-lib" / ".claude" / "settings.json", {"grouped@mp": True})
    _write_enabled(
        ws / "pinky-lib" / "pinky-core" / ".claude" / "settings.local.json",
        {"repolocal@mp": True},
    )
    _write_registry(user_claude, {"registryonly@mp": [{"scope": "user"}]})

    audit = audit_plugins(ws)

    assert set(audit) == {
        "kept@mp",
        "off@mp",
        "grouped@mp",
        "repolocal@mp",
        "registryonly@mp",
    }


def test_audit_records_where_each_plugin_is_enabled_and_disabled(world):
    user_claude, ws = world
    _write_enabled(user_claude / "settings.json", {"p@mp": True})
    _write_enabled(ws / ".claude" / "settings.json", {"p@mp": False})
    _write_enabled(
        ws / "pinky-lib" / "pinky-core" / ".claude" / "settings.json", {"p@mp": True}
    )

    state = audit_plugins(ws)["p@mp"]

    assert state.enabled_at == ("pinky-lib/pinky-core", "user")
    assert state.disabled_at == (".",)
    assert state.is_user_enabled is True


def test_local_settings_get_a_distinct_label(world):
    _, ws = world
    _write_enabled(ws / "pinky-lib" / ".claude" / "settings.local.json", {"p@mp": True})
    assert audit_plugins(ws)["p@mp"].enabled_at == ("pinky-lib (local)",)


# ── the two registries are distinct (IMP-0023-21) ──────────────────────────


def test_registry_scope_is_not_read_as_user_enablement(world):
    user_claude, ws = world
    # pyright-lsp shape: installed at local scope, never in any enabledPlugins map
    _write_registry(
        user_claude,
        {
            "pyright-lsp@official": [
                {"scope": "local", "projectPath": str(ws), "installPath": str(ws)}
            ]
        },
    )

    state = audit_plugins(ws)["pyright-lsp@official"]

    assert state.is_user_enabled is False
    assert state.enabled_at == ()
    assert state.installed_scopes == (f"local:{ws}",)
    assert state.is_ghost is True


def test_ghost_is_a_key_enabled_nowhere(world):
    user_claude, ws = world
    _write_enabled(user_claude / "settings.json", {"inline-thing@inline": False})

    state = audit_plugins(ws)["inline-thing@inline"]

    assert state.marketplace == "inline"
    assert state.is_ghost is True
    assert state.disabled_at == ("user",)


# ── status-line detection (FR-0023-38) ─────────────────────────────────────


def test_ships_status_line_true_when_the_script_is_in_the_install_path(world, tmp_path):
    user_claude, ws = world
    install = tmp_path / "cache" / "pc-statusline"
    (install / "scripts").mkdir(parents=True)
    (install / "scripts" / "statusline.py").write_text("# sl", encoding="utf-8")
    _write_enabled(user_claude / "settings.json", {"pc-statusline@mp": True})
    _write_registry(
        user_claude,
        {"pc-statusline@mp": [{"scope": "user", "installPath": str(install)}]},
    )

    assert audit_plugins(ws)["pc-statusline@mp"].ships_status_line is True


def test_ships_status_line_false_without_the_script_or_without_a_registry_entry(world):
    user_claude, ws = world
    _write_enabled(user_claude / "settings.json", {"plain@mp": True})
    assert audit_plugins(ws)["plain@mp"].ships_status_line is False


# ── required_by: a scope kept alive by another plugin's declared dependency ──


def _install_with_manifest(tmp_path: Path, name: str, manifest: dict) -> Path:
    install = tmp_path / "cache" / name
    (install / ".claude-plugin").mkdir(parents=True)
    (install / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return install


def test_required_by_names_the_dependent_for_a_bare_dependency_id(world, tmp_path):
    user_claude, ws = world
    craft = _install_with_manifest(
        tmp_path, "pc-craft", {"dependencies": ["pc-privacy"]}
    )
    _write_enabled(
        user_claude / "settings.json", {"pc-craft@mp": True, "pc-privacy@mp": True}
    )
    _write_registry(
        user_claude,
        {
            "pc-craft@mp": [{"scope": "user", "installPath": str(craft)}],
            "pc-privacy@mp": [{"scope": "user", "installPath": str(tmp_path / "nope")}],
        },
    )

    audit = audit_plugins(ws)

    assert audit["pc-privacy@mp"].required_by == ("pc-craft",)
    assert audit["pc-craft@mp"].required_by == ()


def test_required_by_matches_a_dependency_written_as_id_at_marketplace(world, tmp_path):
    """`dependencies` may carry `pc-privacy@pinky-agentic-plugins` — the docstring's own example.
    Keyed by the bare id, the audit still surfaces `required by: pc-craft` on `pc-privacy`."""
    user_claude, ws = world
    craft = _install_with_manifest(
        tmp_path, "pc-craft", {"dependencies": ["pc-privacy@pinky-agentic-plugins"]}
    )
    _write_enabled(
        user_claude / "settings.json",
        {
            "pc-craft@pinky-agentic-plugins": True,
            "pc-privacy@pinky-agentic-plugins": True,
        },
    )
    _write_registry(
        user_claude,
        {
            "pc-craft@pinky-agentic-plugins": [
                {"scope": "user", "installPath": str(craft)}
            ]
        },
    )

    audit = audit_plugins(ws)

    assert audit["pc-privacy@pinky-agentic-plugins"].required_by == ("pc-craft",)


def test_a_missing_or_malformed_manifest_never_crashes_the_audit(world, tmp_path):
    user_claude, ws = world
    no_manifest = tmp_path / "cache" / "pc-x"
    no_manifest.mkdir(parents=True)
    broken = tmp_path / "cache" / "pc-y"
    (broken / ".claude-plugin").mkdir(parents=True)
    (broken / ".claude-plugin" / "plugin.json").write_text(
        "{ not json", encoding="utf-8"
    )
    _write_enabled(user_claude / "settings.json", {"pc-x@mp": True, "pc-y@mp": True})
    _write_registry(
        user_claude,
        {
            "pc-x@mp": [{"scope": "user", "installPath": str(no_manifest)}],
            "pc-y@mp": [{"scope": "user", "installPath": str(broken)}],
        },
    )

    audit = audit_plugins(ws)

    assert audit["pc-x@mp"].required_by == ()
    assert audit["pc-y@mp"].required_by == ()


def test_report_prints_the_required_by_line(world, tmp_path, capsys):
    user_claude, ws = world
    craft = _install_with_manifest(
        tmp_path, "pc-craft", {"dependencies": ["pc-privacy"]}
    )
    _write_enabled(
        user_claude / "settings.json", {"pc-craft@mp": True, "pc-privacy@mp": True}
    )
    _write_registry(
        user_claude, {"pc-craft@mp": [{"scope": "user", "installPath": str(craft)}]}
    )

    print_audit_report(audit_plugins(ws))

    out = capsys.readouterr().out
    assert "  required by:     pc-craft" in out


# ── resilience ────────────────────────────────────────────────────────────


def test_a_malformed_settings_file_does_not_blind_the_rest(world):
    user_claude, ws = world
    _write_enabled(user_claude / "settings.json", {"good@mp": True})
    broken = ws / "pinky-lib" / ".claude" / "settings.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{ not json", encoding="utf-8")

    audit = audit_plugins(ws)

    assert audit["good@mp"].enabled_at == ("user",)


def test_no_settings_and_no_registry_yields_empty_audit(world):
    _, ws = world
    assert audit_plugins(ws) == {}


# ── the bare `pinky plugins reconcile` report (FR-0023-32 / FR-0023-33) ─────


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_report_lists_every_plugin_shape_and_writes_nothing(world, tmp_path, capsys):
    """FR-0023-32 + FR-0023-33 oracle: the four shapes all appear, and nothing on disk moves."""
    user_claude, ws = world
    # 1) enabled only in one nested repo
    _write_enabled(
        ws / "pinky-lib" / "pinky-core" / ".claude" / "settings.json",
        {"repo-only@mp": True},
    )
    # 2) only `false`, at user scope
    _write_enabled(user_claude / "settings.json", {"off-at-user@mp": False})
    # 3) an `@inline` key, enabled at the workspace root
    _write_enabled(ws / ".claude" / "settings.json", {"inline-thing@inline": True})
    # 4) present only in the install registry, ships a status line
    install = tmp_path / "cache" / "pc-statusline"
    (install / "scripts").mkdir(parents=True)
    (install / "scripts" / "statusline.py").write_text("# sl", encoding="utf-8")
    _write_registry(
        user_claude,
        {"registry-only@mp": [{"scope": "user", "installPath": str(install)}]},
    )

    before_ws = _snapshot(ws)
    before_home = _snapshot(user_claude)

    print_audit_report(audit_plugins(ws))
    out = capsys.readouterr().out

    assert "=== repo-only@mp ===" in out
    assert "enabled at:      pinky-lib/pinky-core" in out
    assert "=== off-at-user@mp ===" in out
    assert "enabled at:      (nowhere — ghost)" in out
    assert "disabled at:     user" in out
    assert "=== inline-thing@inline ===" in out
    assert "=== registry-only@mp ===" in out
    assert "files installed: user" in out
    assert "ships a status line" in out

    assert _snapshot(ws) == before_ws
    assert _snapshot(user_claude) == before_home


def test_report_on_an_empty_audit_says_so(capsys):
    print_audit_report({})
    assert "No plugin found" in capsys.readouterr().out


# ── stale_labels — the rescope preview, with and without disabled scopes ────


def _state(*, enabled=(), disabled=()) -> plugin_reconcile.PluginState:
    return plugin_reconcile.PluginState(
        plugin_id="p@mp",
        marketplace="mp",
        enabled_at=tuple(enabled),
        disabled_at=tuple(disabled),
        installed_scopes=(),
        ships_status_line=False,
    )


def test_stale_labels_reports_an_enabled_scope_outside_keep(world):
    _, ws = world
    label_map = plugin_reconcile.label_to_settings(ws)
    state = _state(enabled=(".", "pinky-lib/pinky-core"))

    stale = plugin_reconcile.stale_labels(
        state, label_map, keep={str(ws / "pinky-lib" / "pinky-core")}
    )

    assert stale == ["."]


def test_stale_labels_excludes_disabled_scopes_when_asked(world):
    _, ws = world
    label_map = plugin_reconcile.label_to_settings(ws)
    state = _state(enabled=(".",), disabled=("pinky-lib/pinky-core",))
    keep = {str(ws / "bootstrap" / "pinky-bootstrap")}

    assert plugin_reconcile.stale_labels(state, label_map, keep=keep) == [
        ".",
        "pinky-lib/pinky-core",
    ]
    assert plugin_reconcile.stale_labels(
        state, label_map, keep=keep, include_disabled=False
    ) == ["."]


def test_purge_other_enables_include_disabled_false_leaves_the_false_key(world):
    user_claude, ws = world
    repo = ws / "pinky-lib" / "pinky-core"
    _write_enabled(repo / ".claude" / "settings.json", {"p@mp": False})
    label_map = plugin_reconcile.label_to_settings(ws)
    state = _state(disabled=("pinky-lib/pinky-core",))

    plugin_reconcile.purge_other_enables(
        "p@mp",
        state,
        label_map,
        keep={str(user_claude.parent)},
        include_disabled=False,
    )

    assert json.loads((repo / ".claude" / "settings.json").read_text())[
        "enabledPlugins"
    ] == {"p@mp": False}


# ── `--apply` — place each plugin, purge the rest (FR-0023-34..39) ──────────


class _ClaudeCliSim:
    """Faithful stand-in for `claude plugin install/uninstall` — reproduces the measured on-disk
    effect (2026-09-02) so the whole chain runs, and records every argv+cwd for oracles.

    Maintains **both** files the real CLI writes: the scoped `settings.json` `enabledPlugins` key
    and the `installed_plugins.json` registry entry (`{scope, projectPath}`). `_pop_key` touching
    only the first is exactly the gap this card closes — the sim has to model the second for a
    test to see it.
    """

    def __init__(self, home: Path, registry: Path):
        self.home = home
        self.registry = registry
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(self, cmd, **kw):
        cwd = Path(kw["cwd"]) if kw.get("cwd") else None
        self.calls.append((list(cmd), cwd))
        if cmd[:3] == ["claude", "plugin", "install"]:
            self._toggle(cmd, cwd, on=True)
        elif cmd[:3] == ["claude", "plugin", "uninstall"]:
            self._toggle(cmd, cwd, on=False)
        return subprocess.CompletedProcess(cmd, 0)

    def _toggle(self, cmd, cwd, *, on):
        spec = cmd[3]
        scope = cmd[cmd.index("--scope") + 1]
        root = self.home if scope == "user" else cwd
        settings = root / ".claude" / "settings.json"
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
        self._registry_entry(spec, scope, cwd, on=on)

    def _registry_entry(self, spec, scope, cwd, *, on):
        reg = (
            json.loads(self.registry.read_text(encoding="utf-8"))
            if self.registry.is_file()
            else {"version": 2, "plugins": {}}
        )
        entries = reg["plugins"].setdefault(spec, [])
        entry = {"scope": scope}
        if scope != "user" and cwd is not None:
            entry["projectPath"] = str(cwd)
        if on:
            if entry not in entries:
                entries.append(entry)
        else:
            entries[:] = [e for e in entries if e != entry]
            if not entries:
                reg["plugins"].pop(spec, None)
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def apply_world(world, monkeypatch):
    """`world` + a fake `Path.home()` aligned with its `_USER_CLAUDE`, a redirected ledger, a tty,
    and the `claude` CLI simulator. `setup.rules.INSTALLED_PLUGINS_PATH` is repointed at the same
    fixture registry so `resolve_targets_for_plugin` reads what the sim writes."""
    from setup import rules

    user_claude, ws = world
    home = user_claude.parent
    registry = user_claude / "plugins" / "installed_plugins.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(
        state_file, "STATE_FILE_PATH", user_claude / "install-state.json"
    )
    monkeypatch.setattr(rules, "INSTALLED_PLUGINS_PATH", registry)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    sim = _ClaudeCliSim(home, registry)
    monkeypatch.setattr(subprocess, "run", sim)
    return user_claude, ws, sim


def _answers(monkeypatch, seq):
    it = iter(seq)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


def _enabled_in(settings_file: Path) -> dict:
    if not settings_file.is_file():
        return {}
    return json.loads(settings_file.read_text(encoding="utf-8")).get(
        "enabledPlugins", {}
    )


def test_apply_non_interactive_shell_errors_and_writes_nothing(
    apply_world, monkeypatch
):
    user_claude, ws, _ = apply_world
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    _write_enabled(user_claude / "settings.json", {"p@mp": True})
    before = _snapshot(user_claude)

    with pytest.raises(SystemExit):
        apply_reconcile(ws)

    assert _snapshot(user_claude) == before


def test_apply_prompts_once_per_plugin_and_routes_each_answer(apply_world, monkeypatch):
    """FR-0023-34: three plugins, three prompts, each answer routed."""
    user_claude, ws, _sim = apply_world
    _write_enabled(
        user_claude / "settings.json",
        {"keep@mp": True, "drop@mp": True, "stay@mp": True},
    )
    prompts: list[str] = []

    answers = iter(
        ["s", "x", "n", "u"]
    )  # keep→skip, drop→uninstall then refuse, stay→user

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    apply_reconcile(ws)

    target_prompts = [p for p in prompts if "target —" in p]
    assert len(target_prompts) == 3


def test_apply_project_target_purges_user_and_parasitic_repo(apply_world, monkeypatch):
    """FR-0023-35: enabled at user + an unwanted repo, retargeted to the group dir."""
    user_claude, ws, _sim = apply_world
    _write_enabled(user_claude / "settings.json", {"pc-x@mp": True})
    _write_enabled(
        ws / "pinky-lib" / "pinky-snowpark" / ".claude" / "settings.json",
        {"pc-x@mp": True},
    )
    # answer `p` → wizard skips its own scope question → depth 1 → pick "pinky-lib" (the group)
    group_idx = sorted(
        p.name for p in ws.iterdir() if p.is_dir() and not p.name.startswith(".")
    ).index("pinky-lib")
    _answers(monkeypatch, ["p", "1", str(group_idx)])

    apply_reconcile(ws)

    assert "pc-x@mp" not in _enabled_in(user_claude / "settings.json")
    assert "pc-x@mp" not in _enabled_in(
        ws / "pinky-lib" / "pinky-snowpark" / ".claude" / "settings.json"
    )
    assert _enabled_in(ws / "pinky-lib" / ".claude" / "settings.json") == {
        "pc-x@mp": True
    }


def test_apply_project_answer_asks_the_scope_question_only_once(
    apply_world, monkeypatch
):
    """The double-question card: answering `p` in the `--apply` loop must not make
    `run_marketplace_wizard` re-ask `(u)ser/(p)roject` — it goes straight to depth+targets."""
    user_claude, ws, _sim = apply_world
    _write_enabled(user_claude / "settings.json", {"pc-y@mp": True})
    group_idx = sorted(
        p.name for p in ws.iterdir() if p.is_dir() and not p.name.startswith(".")
    ).index("pinky-lib")
    prompts: list[str] = []
    answers = iter(["p", "1", str(group_idx)])

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    apply_reconcile(ws)

    assert not any("Scope —" in p for p in prompts)  # wizard Q1 never shown
    assert sum("target —" in p for p in prompts) == 1  # asked exactly once
    assert _enabled_in(ws / "pinky-lib" / ".claude" / "settings.json") == {
        "pc-y@mp": True
    }
    assert "pc-y@mp" not in _enabled_in(user_claude / "settings.json")


def test_apply_purge_removes_the_registry_entry_of_a_parasitic_project_enable(
    apply_world, monkeypatch
):
    """The `pc-pypi` fallout: a plugin kept at `user` that also carries a parasitic project
    enable *with* an `installed_plugins.json` entry (a dependency install) — purging must clear
    that entry, not just the settings key, or `resolve_targets_for_plugin` (setup/rules.py) keeps
    shipping the plugin's rules to the ghost dir."""
    from setup.rules import resolve_targets_for_plugin

    user_claude, ws, sim = apply_world
    repo = ws / "pinky-lib" / "pinky-core"
    _write_enabled(user_claude / "settings.json", {"pc-dep@mp": True})
    _write_enabled(repo / ".claude" / "settings.json", {"pc-dep@mp": True})
    _write_registry(
        user_claude,
        {
            "pc-dep@mp": [
                {"scope": "user"},
                {"scope": "project", "projectPath": str(repo)},
            ]
        },
    )
    _answers(monkeypatch, ["u"])  # keep pc-dep at user

    apply_reconcile(ws)

    # settings key gone from the repo, kept at user
    assert "pc-dep@mp" not in _enabled_in(repo / ".claude" / "settings.json")
    assert _enabled_in(user_claude / "settings.json") == {"pc-dep@mp": True}
    # registry entry gone — the whole point of the card
    reg = json.loads((user_claude / "plugins" / "installed_plugins.json").read_text())
    assert reg["plugins"]["pc-dep@mp"] == [{"scope": "user"}]
    # and rules.py no longer resolves the ghost dir
    assert resolve_targets_for_plugin("pc-dep", ws) == [ws]
    # removal went through `claude plugin uninstall --scope project`, cwd = the repo
    assert (
        ["claude", "plugin", "uninstall", "pc-dep@mp", "--scope", "project", "--yes"],
        repo,
    ) in sim.calls


def test_apply_uninstall_refused_leaves_the_plugin_untouched(apply_world, monkeypatch):
    """FR-0023-36: answer uninstall, then decline the confirmation."""
    user_claude, ws, sim = apply_world
    _write_enabled(user_claude / "settings.json", {"p@mp": True})
    _answers(monkeypatch, ["x", "n"])

    apply_reconcile(ws)

    assert _enabled_in(user_claude / "settings.json") == {"p@mp": True}
    assert not sim.calls
    assert state_file.posed_value("reconcile:p@mp") is None


def test_apply_uninstall_confirmed_call_sequence_and_inline_key(
    apply_world, monkeypatch
):
    """FR-0023-37: a multi-scope plugin → one `claude plugin uninstall` per registry scope; an
    `@inline` key with no registry entry → popped directly, no CLI call."""
    user_claude, ws, sim = apply_world
    repo = ws / "pinky-lib" / "pinky-core"
    _write_enabled(user_claude / "settings.json", {"multi@mp": True})
    _write_enabled(repo / ".claude" / "settings.json", {"multi@mp": True})
    _write_registry(
        user_claude,
        {
            "multi@mp": [
                {"scope": "user"},
                {"scope": "project", "projectPath": str(repo)},
            ]
        },
    )
    _write_enabled(ws / ".claude" / "settings.json", {"ghost@inline": True})
    _answers(monkeypatch, ["x", "y", "x", "y"])  # multi, then ghost

    apply_reconcile(ws)

    uninstalls = [c for c in sim.calls if c[0][:3] == ["claude", "plugin", "uninstall"]]
    assert [(c[0][4:6], c[1]) for c in uninstalls] == [
        (["--scope", "project"], repo),
        (["--scope", "user"], None),
    ]
    assert "ghost@inline" not in _enabled_in(ws / ".claude" / "settings.json")
    # IMP-0023-22: the direct removal is in the ledger
    keys = json.loads(state_file.STATE_FILE_PATH.read_text(encoding="utf-8"))
    assert any("ghost@inline" in k for k in keys)


def test_apply_status_line_plugin_warns_and_defaults_to_user(
    apply_world, monkeypatch, capsys
):
    """FR-0023-38: a status-line plugin → warning shown, empty answer means user."""
    user_claude, ws, sim = apply_world
    install = user_claude / "cache" / "pc-statusline"
    (install / "scripts").mkdir(parents=True)
    (install / "scripts" / "statusline.py").write_text("# sl", encoding="utf-8")
    _write_enabled(
        ws / "pinky-lib" / "pinky-core" / ".claude" / "settings.json",
        {"pc-statusline@mp": True},
    )
    _write_registry(
        user_claude,
        {"pc-statusline@mp": [{"scope": "user", "installPath": str(install)}]},
    )
    _answers(monkeypatch, [""])  # empty answer → default
    monkeypatch.setattr(
        plugin_reconcile.plugin_install,
        "install_plugin_files",
        lambda *a, **k: sim(
            [
                "claude",
                "plugin",
                "install",
                "pc-statusline@mp",
                "--scope",
                "user",
                "--yes",
            ]
        ),
    )
    apply_reconcile(ws)

    out = capsys.readouterr().out
    assert "status-line" in out and "statusLine" in out
    assert _enabled_in(user_claude / "settings.json") == {"pc-statusline@mp": True}
    assert state_file.posed_value("reconcile:pc-statusline@mp") == "user"


def test_apply_is_replayable_second_run_is_quiet(apply_world, monkeypatch):
    """NFR-0023-14: after a full apply, a second run re-prompts nothing and writes nothing."""
    user_claude, ws, _sim = apply_world
    _write_enabled(user_claude / "settings.json", {"a@mp": True, "b@mp": True})
    _answers(monkeypatch, ["s", "u"])
    apply_reconcile(ws)

    after_first = _snapshot(user_claude)
    calls: list[str] = []
    monkeypatch.setattr("builtins.input", lambda *_: calls.append("asked") or "s")
    apply_reconcile(ws)

    # only the skipped plugin is revisited; the settled one is not
    assert calls == ["asked"]
    assert _snapshot(user_claude) == after_first
