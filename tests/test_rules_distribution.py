"""Distribution des rules — `rules/<plugin>/` → `<target>/.claude/rules/`, une cible par plugin.

`distribute_rules(rules_source, target_root)` est le mécanisme bas niveau : mirror strict d'UN
répertoire source vers UNE cible. `resolve_targets_for_plugin` + `distribute_all_plugin_rules`
résolvent QUELLES cibles depuis `installed_plugins.json` — simuler le comportement qu'aurait
`rules/` si elle était packagée dans le plugin lui-même (elle ne peut pas l'être, format absent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from setup import rules as rules_mod
from setup.common import AGENTIC_HARNESS_DIR


def test_kanban_proactivity_rule_lives_under_pc_kanban_not_pc_core():
    """The kanban rule is inert without pc-kanban installed — it must not ship workspace-wide.

    Guards the 2026-08-28 re-bucketing (FR-0023-17/18): it is the only one of the nine
    ``rules/pc-core/`` files tied to a specific plugin.
    """
    rules_root = AGENTIC_HARNESS_DIR / "rules"
    assert (rules_root / "pc-kanban" / "kanban-proactivity.md").is_file()
    assert not (rules_root / "pc-core" / "kanban-proactivity.md").exists()


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "src_rules"
    src.mkdir()
    return src


# ── distribute_rules — mécanisme bas niveau, une source, une cible ──────────


def test_distributes_and_is_idempotent(source: Path, tmp_path: Path) -> None:
    """Une rule est ajoutée au premier passage, inchangée au second."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"

    first = rules_mod.distribute_rules(source, ws)
    assert first.added == ["workflow.md"]
    assert first.modified == []
    assert first.unchanged == []
    assert (ws / ".claude/rules/workflow.md").read_text(
        encoding="utf-8"
    ) == "# Workflow\n"

    second = rules_mod.distribute_rules(source, ws)
    assert second.added == []
    assert second.modified == []
    assert second.unchanged == ["workflow.md"]


def test_source_change_is_pushed(source: Path, tmp_path: Path) -> None:
    """Une source modifiée réécrit la cible, et compte comme une modification, pas un ajout."""
    (source / "workflow.md").write_text("v1\n", encoding="utf-8")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    (source / "workflow.md").write_text("v2\n", encoding="utf-8")
    report = rules_mod.distribute_rules(source, ws)

    assert report.modified == ["workflow.md"]
    assert report.added == []
    assert (ws / ".claude/rules/workflow.md").read_text(encoding="utf-8") == "v2\n"


def test_plan_does_not_touch_the_filesystem(source: Path, tmp_path: Path) -> None:
    """`apply=False` calcule le même diff mais n'écrit, ne crée ni ne supprime rien."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"

    plan = rules_mod.distribute_rules(source, ws, apply=False)

    assert plan.added == ["workflow.md"]
    assert plan.has_changes
    assert not (ws / ".claude/rules").exists(), (
        "un plan ne doit même pas créer le répertoire cible"
    )

    applied = rules_mod.distribute_rules(source, ws, apply=True)
    assert applied.added == ["workflow.md"]
    assert (ws / ".claude/rules/workflow.md").exists()


def test_orphan_is_purged(source: Path, tmp_path: Path) -> None:
    """Un fichier cible sans source correspondante est supprimé et rapporté."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("plus de source\n", encoding="utf-8")

    report = rules_mod.distribute_rules(source, ws)

    assert report.purged == ["stale.md"], "l'orpheline doit être signalée comme purgée"
    assert not (target / "stale.md").exists(), "une orpheline doit être supprimée"


def test_purge_plan_does_not_delete(source: Path, tmp_path: Path) -> None:
    """`apply=False` liste une orpheline sans la supprimer."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("plus de source\n", encoding="utf-8")

    plan = rules_mod.distribute_rules(source, ws, apply=False)

    assert plan.purged == ["stale.md"]
    assert (target / "stale.md").exists(), "un plan ne supprime rien"


def test_no_changes_reports_no_changes(source: Path, tmp_path: Path) -> None:
    """Une distribution déjà à jour ne rapporte aucun changement."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    report = rules_mod.distribute_rules(source, ws, apply=False)

    assert not report.has_changes
    assert report.unchanged == ["workflow.md"]


def test_missing_source_dir_raises(tmp_path: Path) -> None:
    """Une source absente lève, au lieu de rapporter une distribution vide réussie."""
    with pytest.raises(FileNotFoundError):
        rules_mod.distribute_rules(tmp_path / "nowhere", tmp_path / "ws")


# ── resolve_targets_for_plugin — lit installed_plugins.json ──────────────────


@pytest.fixture
def installed_plugins_file(tmp_path, monkeypatch):
    path = tmp_path / "installed_plugins.json"
    monkeypatch.setattr(rules_mod, "INSTALLED_PLUGINS_PATH", path)

    def write(plugins: dict) -> None:
        path.write_text(
            json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8"
        )

    return write


def test_user_scope_resolves_to_workspace_root(installed_plugins_file, tmp_path):
    installed_plugins_file({"pc-core@pinky-agentic-plugins": [{"scope": "user"}]})
    ws_root = tmp_path / "workspace"

    targets = rules_mod.resolve_targets_for_plugin("pc-core", ws_root)

    assert targets == [ws_root]


def test_non_user_scope_resolves_to_project_path(installed_plugins_file, tmp_path):
    project = tmp_path / "some-repo"
    installed_plugins_file(
        {
            "pc-core@pinky-agentic-plugins": [
                {"scope": "local", "projectPath": str(project)}
            ]
        }
    )

    targets = rules_mod.resolve_targets_for_plugin("pc-core", tmp_path / "workspace")

    assert targets == [project]


def test_multiple_entries_resolve_to_multiple_targets(installed_plugins_file, tmp_path):
    project = tmp_path / "some-repo"
    installed_plugins_file(
        {
            "pc-core@pinky-agentic-plugins": [
                {"scope": "user"},
                {"scope": "local", "projectPath": str(project)},
            ]
        }
    )
    ws_root = tmp_path / "workspace"

    targets = rules_mod.resolve_targets_for_plugin("pc-core", ws_root)

    assert targets == [ws_root, project]


def test_plugin_name_is_matched_before_the_at_sign(installed_plugins_file, tmp_path):
    # Same plugin, different marketplace — still matches on the name alone.
    installed_plugins_file({"pc-core@some-other-marketplace": [{"scope": "user"}]})
    ws_root = tmp_path / "workspace"

    assert rules_mod.resolve_targets_for_plugin("pc-core", ws_root) == [ws_root]


def test_unrelated_plugin_entries_are_ignored(installed_plugins_file, tmp_path):
    installed_plugins_file({"some-other-plugin@marketplace": [{"scope": "user"}]})

    assert rules_mod.resolve_targets_for_plugin("pc-core", tmp_path / "workspace") == []


def test_missing_installed_plugins_file_resolves_to_no_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(rules_mod, "INSTALLED_PLUGINS_PATH", tmp_path / "nowhere.json")

    assert rules_mod.resolve_targets_for_plugin("pc-core", tmp_path / "workspace") == []


# ── discover_plugin_rule_dirs / distribute_all_plugin_rules ─────────────────


def test_discover_plugin_rule_dirs_lists_every_subdir(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-core").mkdir(parents=True)
    (rules_dir / "pinky").mkdir()
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)

    dirs = rules_mod.discover_plugin_rule_dirs()

    assert {d.name for d in dirs} == {"pc-core", "pinky"}


def test_distribute_all_plugin_rules_targets_each_plugin_separately(
    tmp_path, monkeypatch, installed_plugins_file
):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-core").mkdir(parents=True)
    (rules_dir / "pc-core" / "a.md").write_text("A\n", encoding="utf-8")
    (rules_dir / "pinky").mkdir()
    (rules_dir / "pinky" / "b.md").write_text("B\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)

    pinky_lib = tmp_path / "pinky-lib"
    installed_plugins_file(
        {
            "pc-core@pinky-agentic-plugins": [{"scope": "user"}],
            "pinky@pinky-agentic-plugins-private": [
                {"scope": "local", "projectPath": str(pinky_lib)}
            ],
        }
    )
    ws_root = tmp_path / "workspace"

    result = rules_mod.distribute_all_plugin_rules(ws_root)

    assert set(result["pc-core"].keys()) == {ws_root}
    assert set(result["pinky"].keys()) == {pinky_lib}
    assert (ws_root / ".claude/rules/a.md").exists()
    assert (pinky_lib / ".claude/rules/b.md").exists()


def test_distribute_all_plugin_rules_skips_a_plugin_with_no_installed_target(
    tmp_path, monkeypatch, installed_plugins_file
):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-snow").mkdir(parents=True)
    (rules_dir / "pc-snow" / "a.md").write_text("A\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    installed_plugins_file({})  # pc-snow never installed on this machine

    result = rules_mod.distribute_all_plugin_rules(tmp_path / "workspace")

    assert result["pc-snow"] == {}


def _two_plugins_one_target(tmp_path, monkeypatch, installed_plugins_file):
    """`pc-core` + `pc-kanban`, both user-scoped → both resolve to the workspace root."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-core").mkdir(parents=True)
    (rules_dir / "pc-core" / "minimal-code.md").write_text("core\n", encoding="utf-8")
    (rules_dir / "pc-kanban").mkdir()
    (rules_dir / "pc-kanban" / "kanban-proactivity.md").write_text(
        "kanban\n", encoding="utf-8"
    )
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    installed_plugins_file(
        {
            "pc-core@m": [{"scope": "user"}],
            "pc-kanban@m": [{"scope": "user"}],
        }
    )
    return tmp_path / "workspace"


def test_two_plugins_same_target_do_not_purge_each_other(
    tmp_path, monkeypatch, installed_plugins_file
):
    """Same target, disjoint rule sets — the mirror purge spares the co-resident plugin's files."""
    ws = _two_plugins_one_target(tmp_path, monkeypatch, installed_plugins_file)

    result = rules_mod.distribute_all_plugin_rules(ws)

    landed = {p.name for p in (ws / ".claude/rules").glob("*.md")}
    assert landed == {"minimal-code.md", "kanban-proactivity.md"}
    assert result["pc-core"][ws].purged == []
    assert result["pc-kanban"][ws].purged == []


def test_global_purge_still_removes_a_file_no_plugin_owns(
    tmp_path, monkeypatch, installed_plugins_file
):
    """A stale file owned by neither co-resident plugin is still purged."""
    ws = _two_plugins_one_target(tmp_path, monkeypatch, installed_plugins_file)
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "ancient.md").write_text("no plugin owns this\n", encoding="utf-8")

    rules_mod.distribute_all_plugin_rules(ws)

    assert not (target / "ancient.md").exists()


def test_real_rules_ship_kanban_proactivity_iff_pc_kanban_resolves(
    tmp_path, installed_plugins_file
):
    """Real ``agentic-harness/rules/`` tree, synthetic ``installed_plugins.json``.

    Proves the re-bucketing outcome end to end: with ``pc-kanban`` resolving to the target the
    kanban rule lands (and the co-resident ``pc-core`` rules survive); without it, ``pc-kanban``
    resolves to no target and the kanban rule ships nowhere (IMP-0023-12 / IMP-0023-13).
    """
    installed_plugins_file(
        {
            "pc-core@m": [{"scope": "user"}],
            "pc-kanban@m": [{"scope": "user"}],
        }
    )
    with_kanban = tmp_path / "with-kanban"
    rules_mod.distribute_all_plugin_rules(with_kanban)
    landed = {p.name for p in (with_kanban / ".claude/rules").glob("*.md")}
    assert "kanban-proactivity.md" in landed
    assert "minimal-code.md" in landed  # pc-core rule not clobbered by pc-kanban's pass

    installed_plugins_file({"pc-core@m": [{"scope": "user"}]})
    without_kanban = tmp_path / "without-kanban"
    result = rules_mod.distribute_all_plugin_rules(without_kanban)
    assert result["pc-kanban"] == {}
    landed = {p.name for p in (without_kanban / ".claude/rules").glob("*.md")}
    assert "kanban-proactivity.md" not in landed
    assert "minimal-code.md" in landed
