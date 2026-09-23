"""`pinky claude-plugin enable`/`disable` — the plugin x target table, `--scope`, the
plan-then-`[y/N]` convention, and the rules that follow a plugin to its scope.

Boundary fake only: `subprocess.run` (the `claude` CLI). `plugin_enable.run`, `plugin_reconcile`
and `rules` stay real — the sim reproduces the measured on-disk effect of `claude plugin
install/uninstall` (settings key + registry entry), same discipline as `test_plugin_reconcile.py`.
"""

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import cli, plugin_enable, plugin_reconcile, rules, state_file
from setup.plugin_reconcile import _ScopeLabels


class _ClaudeCliSim:
    """Reproduces the measured on-disk effect of `claude plugin install/uninstall`: the scoped
    `settings.json` `enabledPlugins` key, and the `installed_plugins.json` registry entry."""

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


def _write_enabled(settings_file: Path, mapping: dict) -> None:
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps({"enabledPlugins": mapping}), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(plugin_reconcile, "_USER_CLAUDE", home / ".claude")
    monkeypatch.setattr(plugin_reconcile, "_REGISTRY", registry)
    monkeypatch.setattr(rules, "INSTALLED_PLUGINS_PATH", registry)
    monkeypatch.setattr(
        state_file, "STATE_FILE_PATH", home / ".claude" / "install-state.json"
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    ws = tmp_path / "workspace"
    (ws / "bootstrap" / ".git").mkdir(parents=True)
    (ws / "pinky-lib" / "pinky-core" / ".git").mkdir(parents=True)
    (ws / "pinky-lib" / "pinky-snowpark" / ".git").mkdir(parents=True)
    sim = _ClaudeCliSim(home, registry)
    monkeypatch.setattr(subprocess, "run", sim)
    return SimpleNamespace(home=home, ws=ws, registry=registry, sim=sim)


def _enabled_at(settings_dir: Path, spec: str) -> object:
    p = settings_dir / ".claude" / "settings.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text()).get("enabledPlugins", {}).get(spec)


def _canned(monkeypatch, answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_: next(it))


# ── build_rows / build_tree_items — the table, prefilled ──────────────


def test_build_tree_items_indents_a_nested_path_by_segment():
    """The card's own complaint: `bootstrap/pinky-agentic-plugins` must not repeat
    `bootstrap/pinky-agentic-plugins` in full — each path segment is its own (indented) line."""
    rows = [
        plugin_enable.ScopeRow(0, "pc-snow", "user", False),
        plugin_enable.ScopeRow(1, "pc-snow", "bootstrap", True),
        plugin_enable.ScopeRow(2, "pc-snow", "bootstrap/pinky-agentic-plugins", False),
    ]

    items = plugin_enable.build_tree_items(rows)

    assert [(it.text, it.depth, it.key, it.checked) for it in items] == [
        ("user", 0, 0, False),
        ("bootstrap", 0, 1, True),
        ("pinky-agentic-plugins", 1, 2, False),
    ]


def test_build_tree_items_names_the_workspace_root():
    rows = [
        plugin_enable.ScopeRow(0, "pc-snow", ".", True),
        plugin_enable.ScopeRow(1, "pc-snow", "bootstrap", False),
    ]

    items = plugin_enable.build_tree_items(rows, root_name="pinky")

    assert [(it.text, it.depth, it.key) for it in items] == [
        ("pinky (workspace)", 0, 0),
        ("bootstrap", 0, 1),
    ]


def test_build_tree_items_shows_a_non_selectable_grouping_node_with_no_row_of_its_own():
    """A path with no row at its own prefix (only a grandchild target exists) still gets a line,
    for the hierarchy to read — just not a checkable one."""
    rows = [
        plugin_enable.ScopeRow(0, "pc-snow", "pinky-lib/pinky-core", True),
    ]

    items = plugin_enable.build_tree_items(rows)

    assert [(it.text, it.depth, it.selectable, it.key) for it in items] == [
        ("pinky-lib", 0, False, None),
        ("pinky-core", 1, True, 0),
    ]


def test_build_tree_items_headers_each_plugin_only_when_the_batch_names_more_than_one():
    single = plugin_enable.build_tree_items(
        [plugin_enable.ScopeRow(0, "pc-snow", "user", False)]
    )
    assert all(it.selectable for it in single)

    batch = plugin_enable.build_tree_items(
        [
            plugin_enable.ScopeRow(0, "pc-a", "user", False),
            plugin_enable.ScopeRow(1, "pc-b", "user", False),
        ]
    )
    assert [(it.text, it.selectable) for it in batch] == [
        ("pc-a", False),
        ("user", True),
        ("pc-b", False),
        ("user", True),
    ]


def test_apply_checklist_result_maps_back_by_row_index_only():
    rows = [
        plugin_enable.ScopeRow(0, "pc-snow", "user", False),
        plugin_enable.ScopeRow(1, "pc-snow", "pinky-lib", True),
    ]
    items = plugin_enable.build_tree_items(rows)

    updated = plugin_enable.apply_checklist_result(rows, items, [True, False])

    assert plugin_enable._desired_labels(updated, "pc-snow") == {"user"}


def test_table_is_prefilled_from_a_project_enable_already_known_to_settings(env):
    _write_enabled(
        env.ws / "pinky-lib" / ".claude" / "settings.json", {"pc-snow": True}
    )
    audit = plugin_reconcile.audit_plugins(env.ws)
    label_map = plugin_reconcile.label_to_settings(env.ws)

    rows = plugin_enable.build_rows([("pc-snow", audit["pc-snow"])], label_map)

    by_label = {row.label: row.checked for row in rows}
    assert by_label["pinky-lib"] is True
    assert by_label["."] is False
    assert by_label["user"] is False


def test_a_local_settings_enable_is_never_a_row(env):
    """`pc-autodiscovery`'s session state never appears in the table."""
    _write_enabled(
        env.ws / "pinky-lib" / ".claude" / "settings.local.json", {"pc-snow": True}
    )
    audit = plugin_reconcile.audit_plugins(env.ws)
    label_map = plugin_reconcile.label_to_settings(env.ws)

    rows = plugin_enable.build_rows([("pc-snow", audit["pc-snow"])], label_map)

    assert all("(local)" not in row.label for row in rows)
    assert all(not row.checked for row in rows)


def test_filter_checked_keeps_only_checked_rows_and_reindexes():
    rows = [
        plugin_enable.ScopeRow(0, "pc-a", "user", True),
        plugin_enable.ScopeRow(1, "pc-a", ".", False),
        plugin_enable.ScopeRow(2, "pc-b", "user", False),
        plugin_enable.ScopeRow(3, "pc-b", ".", True),
    ]

    filtered = plugin_enable.filter_checked(rows)

    assert filtered == [
        plugin_enable.ScopeRow(0, "pc-a", "user", True),
        plugin_enable.ScopeRow(1, "pc-b", ".", True),
    ]


# ── pick_plugins — the "no name" checkbox list ────────────────────


def test_build_plugin_pick_rows_prechecks_only_installed_names():
    rows = plugin_enable.build_plugin_pick_rows(
        curated_names=["pc-a", "pc-b", "pc-c"], installed_names=["pc-b"]
    )

    by_name = {row.name: row.checked for row in rows}
    assert by_name == {"pc-a": False, "pc-b": True, "pc-c": False}


def test_build_plugin_pick_rows_checks_everything_with_no_installed_plugin():
    """`installed_plugins.json` absent or empty → the curated list is entirely
    checked, not just the (nonexistent) installed subset."""
    rows = plugin_enable.build_plugin_pick_rows(
        curated_names=["pc-a", "pc-b"], installed_names=[]
    )

    assert all(row.checked for row in rows)


def _check_all(items, title, **kwargs):
    """A fake `picker`: every row confirmed checked, regardless of how it was prefilled — stands
    in for an interactive session where the user ticked everything before hitting enter."""
    return [True for _ in items]


def _keep_as_shown(items, title, **kwargs):
    """A fake `picker`: confirms every row exactly as prefilled — the "enter, no toggle" case."""
    return [item.checked for item in items]


def test_pick_plugins_returns_the_checked_names_after_a_toggle(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    picked = plugin_enable.pick_plugins(
        curated_names=["pc-a", "pc-b"], installed_names=["pc-b"], picker=_check_all
    )

    assert set(picked) == {"pc-a", "pc-b"}


def test_pick_plugins_keeps_the_default_selection_on_enter(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    picked = plugin_enable.pick_plugins(
        curated_names=["pc-a", "pc-b"], installed_names=["pc-b"], picker=_keep_as_shown
    )

    assert picked == ["pc-b"]


def _interrupted(items, title, **kwargs):
    raise KeyboardInterrupt


def test_pick_plugins_lets_ctrl_c_through(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with pytest.raises(KeyboardInterrupt):
        plugin_enable.pick_plugins(
            curated_names=["pc-a"], installed_names=[], picker=_interrupted
        )


def test_pick_plugins_refuses_without_a_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(SystemExit):
        plugin_enable.pick_plugins(curated_names=["pc-a"], installed_names=[])


def test_pick_plugins_refuses_with_nothing_to_pick_from(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with pytest.raises(SystemExit):
        plugin_enable.pick_plugins(curated_names=[], installed_names=[])


# ── desired_from_scope_flags — --scope bypasses the table ─────────────────


def test_scope_flag_enable_adds_to_what_is_already_enabled():
    desired = plugin_enable._desired_from_scope_flags(
        {"."}, {"pinky-lib"}, action="enable"
    )
    assert desired == {".", "pinky-lib"}


def test_scope_flag_disable_removes_only_the_named_labels():
    desired = plugin_enable._desired_from_scope_flags(
        {".", "pinky-lib"}, {"pinky-lib"}, action="disable"
    )
    assert desired == {"."}


def test_scope_flag_run_asks_no_question_at_all(env, monkeypatch):
    monkeypatch.setattr(
        "builtins.input", lambda *_: pytest.fail("--scope must ask nothing")
    )

    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert _enabled_at(env.ws / "pinky-lib", "pc-snow") is True


# ── inherited labels — children pc-autodiscovery enables, never auto-removed ──


def test_inherited_labels_lists_children_of_a_checked_ancestor(env):
    label_map = plugin_reconcile.label_to_settings(env.ws)
    desired = {".", "pinky-lib/pinky-core", "pinky-lib/pinky-snowpark"}

    inherited = plugin_enable._inherited_labels(desired, label_map, env.ws)

    assert inherited == ["pinky-lib/pinky-core", "pinky-lib/pinky-snowpark"]


def _diff_with_inherited(added):
    return plugin_enable.ScopeDiff(
        added=added,
        removed=[],
        unchanged=[".", "pinky-lib/pinky-core"]
        if not added
        else ["pinky-lib/pinky-core"],
        inherited=["pinky-lib/pinky-core"],
    )


def test_render_scope_plan_names_inherited_children_with_autodiscovery():
    diff = _diff_with_inherited(["."])
    assert plugin_enable.render_scope_plan("pc-snow", diff, autodiscovery=True) == (
        "pc-snow:\n"
        "  add: .\n"
        "  unchanged: pinky-lib/pinky-core\n"
        "  inherited via pc-autodiscovery: pinky-lib/pinky-core"
    )


def test_render_scope_plan_says_nothing_of_inheritance_without_autodiscovery():
    """Claude Code reads `enabledPlugins` in the opened directory only — without pc-autodiscovery a
    child enable is what makes the plugin active there, so nothing is inherited to report."""
    diff = _diff_with_inherited(["."])
    assert plugin_enable.render_scope_plan("pc-snow", diff) == (
        "pc-snow:\n  add: .\n  unchanged: pinky-lib/pinky-core"
    )


def test_render_scope_plan_says_nothing_to_do_on_an_empty_diff():
    diff = plugin_enable.ScopeDiff(added=[], removed=[], unchanged=["."], inherited=[])
    assert (
        plugin_enable.render_scope_plan("pc-snow", diff) == "pc-snow:\n  nothing to do"
    )


def test_render_scope_plan_surfaces_inheritance_even_with_nothing_toggled():
    diff = _diff_with_inherited([])
    assert plugin_enable.render_scope_plan("pc-snow", diff, autodiscovery=True) == (
        "pc-snow:\n"
        "  unchanged: ., pinky-lib/pinky-core\n"
        "  inherited via pc-autodiscovery: pinky-lib/pinky-core"
    )


def test_picker_title_explains_inheritance_with_autodiscovery():
    assert plugin_enable.picker_title("enable", autodiscovery=True) == (
        "enable — a checked folder also covers every folder below it (pc-autodiscovery)"
    )


def test_picker_title_is_the_bare_action_without_autodiscovery():
    assert plugin_enable.picker_title("enable", autodiscovery=False) == "enable"


def test_autodiscovery_active_reads_the_audit():
    on = replace(
        plugin_enable._empty_state("pc-autodiscovery@m", "m"),
        enabled_at=_ScopeLabels(("user",)),
    )
    assert plugin_enable.autodiscovery_active({"pc-autodiscovery@m": on}) is True
    assert plugin_enable.autodiscovery_active({}) is False


def test_render_scope_plan_notes_the_prune_side_effect_of_removing_user_scope():
    """Fix 1: `drop_user_scope` also prunes now-unneeded dependencies — the plan says so, since
    that write is not otherwise shown before `[y/N]`."""
    diff = plugin_enable.ScopeDiff(
        added=[], removed=["user"], unchanged=[], inherited=[]
    )
    assert plugin_enable.render_scope_plan("pc-snow", diff) == (
        "pc-snow:\n"
        "  remove: user\n"
        "  note: removing the user scope may also prune now-unneeded dependencies "
        "(`claude plugin prune`)"
    )


# ── enable/disable at a project scope — the write side ─────────────────────────────────


def test_enable_at_scope_writes_the_project_settings_and_registry(env):
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert _enabled_at(env.ws / "pinky-lib", "pc-snow") is True
    reg = json.loads(env.registry.read_text())
    assert reg["plugins"]["pc-snow"] == [
        {"scope": "project", "projectPath": str(env.ws / "pinky-lib")}
    ]


def test_disable_at_scope_removes_the_project_enable_and_registry_entry(env):
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    plugin_enable.run(
        "disable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert _enabled_at(env.ws / "pinky-lib", "pc-snow") is None
    reg = json.loads(env.registry.read_text())
    assert reg["plugins"] == {}


def test_disable_table_prefilled_and_unchecking_removes_the_enable(env, monkeypatch):
    """The disable table starts from the current scopes; toggling a checked row off
    removes exactly that enable."""
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    def uncheck_pinky_lib(items, title, **kwargs):
        return [it.checked and it.text != "pinky-lib" for it in items]

    _canned(monkeypatch, ["y"])

    plugin_enable.run(
        "disable",
        ["pc-snow"],
        env.ws,
        user_rules_dir=env.home / "no-user-rules",
        picker=uncheck_pinky_lib,
    )

    assert _enabled_at(env.ws / "pinky-lib", "pc-snow") is None


# ── return value: outcome + which specs were actually applied ──────────────────────────


def test_run_returns_the_applied_spec_on_success(env):
    result = plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert result.outcome == "applied"
    assert result.applied == ["pc-snow"]
    assert result.wire is True


def test_run_reports_nothing_to_do_but_still_wireable(env):
    """A second identical run changes nothing, but the plugin IS on disk and enabled exactly as
    desired — a caller like `install` re-wiring a statusLine path after `claude plugin update`
    must still be able to tell this apart from a declined or dry-run plan (neither of which ever
    wrote anything, so nothing to re-wire)."""
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    result = plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert result.outcome == "nothing"
    assert result.applied == []
    assert result.wire is True


def test_run_reports_dry_run_as_not_wireable(env):
    result = plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        dry_run=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert result.outcome == "dry_run"
    assert result.applied == []
    assert result.wire is False
    assert not (env.ws / "pinky-lib" / ".claude" / "settings.json").exists()


def test_run_reports_a_declined_plan_as_not_wireable(env, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    _canned(monkeypatch, ["n"])

    result = plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        user_rules_dir=env.home / "no-user-rules",
    )

    assert result.outcome == "declined"
    assert result.applied == []
    assert result.wire is False


# ── rules follow the plugin to its scope ──────────────────────────


@pytest.fixture
def rule_shipped(env, monkeypatch, tmp_path):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-snow").mkdir(parents=True)
    (rules_dir / "pc-snow" / "rule_1.md").write_text("# rule\n", encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_DIR", rules_dir)
    return env


def test_enable_distributes_the_plugins_rules_at_the_same_scope(rule_shipped):
    env = rule_shipped

    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert (env.ws / "pinky-lib" / ".claude" / "rules" / "rule_1.md").read_text(
        encoding="utf-8"
    ) == "# rule\n"
    plan = rules.distribute_all_plugin_rules(
        env.ws, apply=False, user_rules_dir=env.home / "no-user-rules"
    )
    assert not plan["pc-snow"][env.ws / "pinky-lib"].has_changes


def test_disable_removes_the_plugins_rules_at_that_scope(rule_shipped):
    env = rule_shipped
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    plugin_enable.run(
        "disable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert not (env.ws / "pinky-lib" / ".claude" / "rules" / "rule_1.md").exists()


def test_disabling_an_inline_only_plugin_spares_a_co_resident_inline_only_sibling(
    env, monkeypatch, tmp_path
):
    """Bloquant 1+2 regression: two plugins enabled through a bare `@inline` settings key (no
    `installed_plugins.json` entry at all) at the same label. Disabling one must purge exactly
    its own rules there — not the sibling's, and not "nowhere" (a registry-only read of "where
    the plugin resolves" never sees either of them, so their rules would never be visited again)."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-a").mkdir(parents=True)
    (rules_dir / "pc-a" / "a.md").write_text("A\n", encoding="utf-8")
    (rules_dir / "pc-b").mkdir(parents=True)
    (rules_dir / "pc-b" / "b.md").write_text("B\n", encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_DIR", rules_dir)
    _write_enabled(env.ws / ".claude" / "settings.json", {"pc-a": True, "pc-b": True})
    target_rules = env.ws / ".claude" / "rules"
    target_rules.mkdir(parents=True)
    (target_rules / "a.md").write_text("A\n", encoding="utf-8")
    (target_rules / "b.md").write_text("B\n", encoding="utf-8")

    plugin_enable.run(
        "disable",
        ["pc-a"],
        env.ws,
        scope=["."],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert not (target_rules / "a.md").exists()
    assert (target_rules / "b.md").read_text(encoding="utf-8") == "B\n"
    assert _enabled_at(env.ws, "pc-a") is None
    assert _enabled_at(env.ws, "pc-b") is True


def test_batch_enable_of_two_new_plugins_keeps_both_plugins_rules(
    env, monkeypatch, tmp_path
):
    """Renvoi 2 regression: naming two plugins in one `run()` call — the second plugin's own
    apply pass must not purge the first plugin's rules at the shared target, even though the
    sibling-ownership snapshot was taken before either plugin was actually enabled."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-a").mkdir(parents=True)
    (rules_dir / "pc-a" / "a.md").write_text("A\n", encoding="utf-8")
    (rules_dir / "pc-b").mkdir(parents=True)
    (rules_dir / "pc-b" / "b.md").write_text("B\n", encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_DIR", rules_dir)

    plugin_enable.run(
        "enable",
        ["pc-a", "pc-b"],
        env.ws,
        scope=["."],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    target_rules = env.ws / ".claude" / "rules"
    assert (target_rules / "a.md").read_text(encoding="utf-8") == "A\n"
    assert (target_rules / "b.md").read_text(encoding="utf-8") == "B\n"


def test_a_plugin_not_installed_writes_no_rule_file(tmp_path, monkeypatch):
    """Unaffected by enable/disable ever running for this plugin."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-toto").mkdir(parents=True)
    (rules_dir / "pc-toto" / "rule_1.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(rules, "RULES_DIR", rules_dir)
    monkeypatch.setattr(rules, "INSTALLED_PLUGINS_PATH", tmp_path / "nowhere.json")

    plan = rules.distribute_all_plugin_rules(tmp_path / "ws")

    assert plan["pc-toto"] == {}


# ── the plan-then-[y/N] convention ───────────────────────────────


def _check_dot(items, title, **kwargs):
    return [it.checked or it.text.endswith(" (workspace)") for it in items]


def test_a_declined_confirmation_writes_nothing(env, monkeypatch, capsys):
    _canned(monkeypatch, ["n"])  # refuse

    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        user_rules_dir=env.home / "no-user-rules",
        picker=_check_dot,
    )

    assert env.sim.calls == []
    assert "cancelled." in capsys.readouterr().out


def test_yes_skips_the_confirmation(env):
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )
    assert _enabled_at(env.ws / "pinky-lib", "pc-snow") is True


def test_non_interactive_without_scope_errors_even_under_yes(env, monkeypatch):
    """Fix 2: `--yes` only ever skips the `[y/N]` confirmation — it must not be read as "keep
    everything as shown" when there was never a table to show (no tty, no `--scope`). Silently
    no-op'ing here would let a CI script believe an intended change actually happened."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(SystemExit):
        plugin_enable.run(
            "enable",
            ["pc-snow"],
            env.ws,
            yes=True,
            user_rules_dir=env.home / "no-user-rules",
        )

    assert env.sim.calls == []


def test_dry_run_prints_the_plan_and_writes_nothing(env, capsys):
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        dry_run=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert env.sim.calls == []
    assert "add: pinky-lib" in capsys.readouterr().out


def test_replaying_the_same_command_says_nothing_to_do_and_writes_nothing(env, capsys):
    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )
    capsys.readouterr()
    calls_before = len(env.sim.calls)

    plugin_enable.run(
        "enable",
        ["pc-snow"],
        env.ws,
        scope=["pinky-lib"],
        yes=True,
        user_rules_dir=env.home / "no-user-rules",
    )

    assert len(env.sim.calls) == calls_before
    assert "nothing to do" in capsys.readouterr().out


# ── cli.py dispatch: the Workspace line, and no-name refusal ───────────────────────────


def test_cli_prints_the_workspace_line_first(env, monkeypatch, capsys):
    monkeypatch.setattr(cli, "sys", sys)
    monkeypatch.delenv("PINKY_WORKSPACE_ROOT", raising=False)

    cli.main(
        [
            "--plugin-enable",
            "pc-snow",
            "--workspace",
            str(env.ws),
            "--scope",
            "pinky-lib",
            "--yes",
            "--rules-dir",
            str(env.home / "no-user-rules"),
        ]
    )

    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line == f"Workspace: {env.ws.resolve()} (via --workspace)"


def test_enable_with_no_plugin_name_errors_plainly(env):
    with pytest.raises(SystemExit):
        plugin_enable.run("enable", [], env.ws)


# ── --rules-dir: expanded/resolved like --workspace, warns when it does not exist (fix 4) ──


def test_rules_dir_arg_is_expanded_and_resolved(tmp_path, monkeypatch):
    existing = tmp_path / "user-rules"
    existing.mkdir()
    monkeypatch.chdir(tmp_path)

    assert cli._resolve_rules_dir_arg("user-rules") == existing.resolve()


def test_rules_dir_arg_none_stays_none():
    assert cli._resolve_rules_dir_arg(None) is None


def test_a_missing_rules_dir_is_still_returned_but_warns(tmp_path, capsys):
    missing = tmp_path / "nowhere"

    resolved = cli._resolve_rules_dir_arg(str(missing))

    assert resolved == missing.resolve()
    assert "does not exist" in capsys.readouterr().err


# ── render_rules_plan: named files per target, unchanged targets summarized ─────


def _rules_reports(ws: Path) -> dict[Path, rules.RulesReport]:
    return {
        ws: rules.RulesReport(modified=["kanban-proactivity.md"], purged=["old.md"]),
        ws / "bootstrap": rules.RulesReport(added=["a.md", "b.md"]),
        ws / "ops": rules.RulesReport(unchanged=["a.md"]),
        ws / "pinky-lib": rules.RulesReport(),
    }


def test_render_rules_plan_names_each_file_and_summarizes_unchanged_targets(tmp_path):
    ws = tmp_path / "pinky"

    text = plugin_enable.render_rules_plan(_rules_reports(ws), workspace_root=ws)

    assert text == (
        "  rules → pinky (workspace): updated kanban-proactivity.md · removed old.md\n"
        "  rules → bootstrap: added a.md, b.md\n"
        "  ✓ rules up to date (2 targets)"
    )


def test_render_rules_plan_verbose_lists_each_unchanged_target(tmp_path):
    ws = tmp_path / "pinky"

    text = plugin_enable.render_rules_plan(
        _rules_reports(ws), workspace_root=ws, verbose=True
    )

    assert text == (
        "  rules → pinky (workspace): updated kanban-proactivity.md · removed old.md\n"
        "  rules → bootstrap: added a.md, b.md\n"
        "  rules → ops: ✓ up to date\n"
        "  rules → pinky-lib: ✓ up to date"
    )


def test_render_rules_plan_singular_summary(tmp_path):
    ws = tmp_path / "pinky"

    text = plugin_enable.render_rules_plan(
        {ws: rules.RulesReport(unchanged=["a.md"])}, workspace_root=ws
    )

    assert text == "  ✓ rules up to date (1 target)"
