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


def test_kanban_proactivity_rule_is_distributed_from_neither_pc_kanban_nor_pc_core():
    """The kanban rule is no longer shipped by ``rules/``.

    It now reaches the main session through the pc-kanban plugin's SessionStart hook, so a copy
    under ``rules/pc-kanban/`` or ``rules/pc-core/`` would load it twice.
    """
    rules_root = AGENTIC_HARNESS_DIR / "rules"
    assert not (rules_root / "pc-kanban" / "kanban-proactivity.md").exists()
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


# ── two-level rules: the user's override dir on top of the shipped rules ──


def test_user_rules_dir_adds_a_rule(tmp_path, monkeypatch, installed_plugins_file):
    """A file added under the user's <plugin>/ dir is distributed alongside the
    shipped rules, not instead of them."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-toto").mkdir(parents=True)
    (rules_dir / "pc-toto" / "shipped.md").write_text("shipped\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    user_dir = tmp_path / "user-rules"
    (user_dir / "pc-toto").mkdir(parents=True)
    (user_dir / "pc-toto" / "extra.md").write_text("extra\n", encoding="utf-8")
    installed_plugins_file({"pc-toto@m": [{"scope": "user"}]})
    ws = tmp_path / "workspace"

    result = rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=user_dir)

    landed = {p.name for p in (ws / ".claude/rules").glob("*.md")}
    assert landed == {"shipped.md", "extra.md"}
    assert result["pc-toto"][ws].added == ["extra.md", "shipped.md"]


def test_user_rules_dir_file_of_same_name_replaces_shipped_rule(
    tmp_path, monkeypatch, installed_plugins_file
):
    """A user file with the same name as a shipped rule wins — the distributed
    content is the user's, byte for byte."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-toto").mkdir(parents=True)
    (rules_dir / "pc-toto" / "shipped.md").write_text(
        "shipped version\n", encoding="utf-8"
    )
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    user_dir = tmp_path / "user-rules"
    (user_dir / "pc-toto").mkdir(parents=True)
    (user_dir / "pc-toto" / "shipped.md").write_text("user version\n", encoding="utf-8")
    installed_plugins_file({"pc-toto@m": [{"scope": "user"}]})
    ws = tmp_path / "workspace"

    rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=user_dir)

    assert (ws / ".claude/rules/shipped.md").read_text(encoding="utf-8") == (
        "user version\n"
    )


def test_user_rules_dir_exclude_marker_drops_a_shipped_rule(
    tmp_path, monkeypatch, installed_plugins_file
):
    """`<name>.md.exclude` (never itself globbed as a rule) removes a shipped rule
    from distribution."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-toto").mkdir(parents=True)
    (rules_dir / "pc-toto" / "unwanted.md").write_text("nope\n", encoding="utf-8")
    (rules_dir / "pc-toto" / "kept.md").write_text("yes\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    user_dir = tmp_path / "user-rules"
    (user_dir / "pc-toto").mkdir(parents=True)
    (user_dir / "pc-toto" / "unwanted.md.exclude").write_text("", encoding="utf-8")
    installed_plugins_file({"pc-toto@m": [{"scope": "user"}]})
    ws = tmp_path / "workspace"

    rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=user_dir)

    landed = {p.name for p in (ws / ".claude/rules").glob("*.md")}
    assert landed == {"kept.md"}
    assert "unwanted.md.exclude" not in landed


def test_user_rules_dir_default_path_is_under_dot_claude(monkeypatch):
    """With no `--rules-dir`, the override root is `~/.claude/rules`
    (`USER_RULES_DIR`, resolved from `Path.home()` at import time like every other pinky
    user-scope path — see `INSTALLED_PLUGINS_PATH` above)."""
    monkeypatch.setattr(rules_mod, "USER_RULES_DIR", Path("/fake-home/.claude/rules"))
    assert rules_mod.resolve_user_rules_dir() == Path("/fake-home/.claude/rules")


def test_user_rules_dir_explicit_path_overrides_the_default():
    """An explicit `--rules-dir` path wins over the default."""
    explicit = Path("/somewhere/else")
    assert rules_mod.resolve_user_rules_dir(explicit) == explicit


def test_a_rules_dir_for_an_uninstalled_plugin_still_writes_nothing_with_a_user_override(
    tmp_path, monkeypatch, installed_plugins_file
):
    """Holds through the two-level merge: a plugin never installed on this machine still
    resolves to no target, user override or not."""
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-toto").mkdir(parents=True)
    (rules_dir / "pc-toto" / "a.md").write_text("A\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    user_dir = tmp_path / "user-rules"
    (user_dir / "pc-toto").mkdir(parents=True)
    (user_dir / "pc-toto" / "b.md").write_text("B\n", encoding="utf-8")
    installed_plugins_file({})

    result = rules_mod.distribute_all_plugin_rules(
        tmp_path / "workspace", user_rules_dir=user_dir
    )

    assert result["pc-toto"] == {}


def test_real_rules_ship_pc_snow_rules_iff_pc_snow_resolves(
    tmp_path, installed_plugins_file
):
    """Real ``agentic-harness/rules/`` tree, synthetic ``installed_plugins.json``.

    Proves the re-bucketing outcome end to end: with ``pc-snow`` resolving to the target its rule
    lands (and the co-resident ``pc-core`` rules survive); without it, ``pc-snow`` resolves to no
    target and its rule ships nowhere.
    """
    installed_plugins_file(
        {
            "pc-core@m": [{"scope": "user"}],
            "pc-snow@m": [{"scope": "user"}],
        }
    )
    with_snow = tmp_path / "with-snow"
    rules_mod.distribute_all_plugin_rules(with_snow)
    landed = {p.name for p in (with_snow / ".claude/rules").glob("*.md")}
    assert "snowpark.md" in landed
    assert "minimal-code.md" in landed  # pc-core rule not clobbered by pc-snow's pass

    installed_plugins_file({"pc-core@m": [{"scope": "user"}]})
    without_snow = tmp_path / "without-snow"
    result = rules_mod.distribute_all_plugin_rules(without_snow)
    assert result["pc-snow"] == {}
    landed = {p.name for p in (without_snow / ".claude/rules").glob("*.md")}
    assert "snowpark.md" not in landed
    assert "minimal-code.md" in landed


# ── ancestor coverage: Claude Code already loads a parent's rules ──


def _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file, *project_paths):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-kanban").mkdir(parents=True)
    (rules_dir / "pc-kanban" / "kanban-proactivity.md").write_text(
        "kanban\n", encoding="utf-8"
    )
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    installed_plugins_file(
        {
            "pc-kanban@m": [
                {"scope": "project", "projectPath": str(p)} for p in project_paths
            ]
        }
    )


def test_a_target_under_another_target_gets_no_copy(
    tmp_path, monkeypatch, installed_plugins_file
):
    ws, group = tmp_path / "ws", tmp_path / "ws" / "group"
    _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file, ws, group)

    result = rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=tmp_path / "u")

    assert set(result["pc-kanban"]) == {ws}
    assert (ws / ".claude/rules/kanban-proactivity.md").exists()
    assert not (group / ".claude").exists()


def test_a_covered_target_loses_its_stale_copy_and_keeps_hand_written_rules(
    tmp_path, monkeypatch, installed_plugins_file
):
    ws, group = tmp_path / "ws", tmp_path / "ws" / "group"
    _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file, ws, group)
    (group / ".claude/rules").mkdir(parents=True)
    (group / ".claude/rules/kanban-proactivity.md").write_text(
        "old\n", encoding="utf-8"
    )
    (group / ".claude/rules/local.md").write_text("mine\n", encoding="utf-8")

    result = rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=tmp_path / "u")

    assert result["pc-kanban"][group] == rules_mod.RulesReport(
        purged=["kanban-proactivity.md"]
    )
    assert sorted(p.name for p in (group / ".claude/rules").iterdir()) == ["local.md"]


def test_sibling_targets_both_get_a_copy(tmp_path, monkeypatch, installed_plugins_file):
    a, b = tmp_path / "ws" / "a", tmp_path / "ws" / "b"
    _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file, a, b)

    result = rules_mod.distribute_all_plugin_rules(
        tmp_path / "ws", user_rules_dir=tmp_path / "u"
    )

    assert set(result["pc-kanban"]) == {a, b}


def test_enable_path_skips_a_present_target_under_a_present_ancestor(
    tmp_path, monkeypatch, installed_plugins_file
):
    ws, group = tmp_path / "ws", tmp_path / "ws" / "group"
    _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file)

    reports = rules_mod.rules_report_for_plugin_at_targets(
        "pc-kanban", [ws, group], [], ws, user_rules_dir=tmp_path / "u"
    )

    assert reports[ws] == rules_mod.RulesReport(added=["kanban-proactivity.md"])
    assert reports[group] == rules_mod.RulesReport()
    assert not (group / ".claude").exists()


def test_enable_path_restores_the_copy_once_the_ancestor_is_dropped(
    tmp_path, monkeypatch, installed_plugins_file
):
    ws, group = tmp_path / "ws", tmp_path / "ws" / "group"
    _pc_kanban_at(tmp_path, monkeypatch, installed_plugins_file)

    reports = rules_mod.rules_report_for_plugin_at_targets(
        "pc-kanban", [group], [ws, group], ws, user_rules_dir=tmp_path / "u"
    )

    assert reports[group] == rules_mod.RulesReport(added=["kanban-proactivity.md"])
    assert (group / ".claude/rules/kanban-proactivity.md").exists()


LAZY_BODY = "# Tests\n\nBody line.\n"
LAZY_SOURCE = (
    "---\n"
    "paths:\n"
    '  - "**/*.py"\n'
    "_load_conditions:\n"
    '  - "a Python file"\n'
    "  - any test\n"
    "---\n\n" + LAZY_BODY
)


def _stub_text(
    ws: Path, name: str = "tests.md", conditions: str = "a Python file or any test"
) -> str:
    content = (ws / ".claude/rules-content" / name).resolve()
    return f"Your FIRST action, {conditions}, MUST be to `Read` `{content}` in full.\n"


def _lazy(source: Path, text: str = LAZY_SOURCE) -> None:
    (source / "tests.md").write_text(text, encoding="utf-8")


def test_rule_without_load_conditions_is_copied_byte_identical(source, tmp_path):
    text = '---\npaths:\n  - "x"\n---\n\nbody\n'
    (source / "plain.md").write_text(text, encoding="utf-8")
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/plain.md").read_text(encoding="utf-8") == text
    assert not (ws / ".claude/rules-content").exists()


def test_lazy_rule_with_paths_writes_stub_and_content(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"

    report = rules_mod.distribute_rules(source, ws)

    assert report.added == ["tests.md"]
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY
    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n---\n\n' + _stub_text(ws)
    )


def test_lazy_rule_without_paths_has_a_stub_with_no_frontmatter(source, tmp_path):
    _lazy(source, '---\n_load_conditions:\n  - "the kanban board"\n---\n\nBody\n')
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == _stub_text(
        ws, conditions="the kanban board"
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == "Body\n"


@pytest.mark.parametrize(
    "clause",
    [
        "if you are fixing a bug, extending or modifying code, or reviewing code",
        "before adding an ADR",
        "Python files",
    ],
)
def test_free_clause_is_accepted_and_spliced_into_the_stub(source, tmp_path, clause):
    _lazy(source, f'---\n_load_conditions:\n  - "{clause}"\n---\n\nBody\n')
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == _stub_text(
        ws, conditions=clause
    )


def test_a_long_clause_is_accepted(source, tmp_path):
    clause = "if you are " + "x" * 200
    _lazy(source, f"---\n_load_conditions:\n  - {clause}\n---\n\nBody\n")

    report = rules_mod.distribute_rules(source, tmp_path / "ws")

    assert report == rules_mod.RulesReport(added=["tests.md"])


@pytest.mark.parametrize(
    "items",
    [
        [],  # empty list
        ['""'],  # blank item
        ["''"],
        ['"   "'],
        ['"if you edit `code`"'],  # backtick breaks the stub's own quoting
        ['"when the build is red."'],  # the frame owns the punctuation
        ['"if you edit,"'],
        ['"if you edit;"'],
        ['"if you edit:"'],
        ["> folded scalar"],  # YAML indicators are not supported
        ["| literal scalar"],
        ["&anchor if you edit"],
        ["*alias"],
        ["!tag if you edit"],
        ["if you edit\n    continued on the next line"],  # truncated clause
    ],
)
def test_invalid_condition_is_refused_and_nothing_is_written(source, tmp_path, items):
    body = "".join(f"  - {c}\n" for c in items).replace("\\n", "\n")
    _lazy(source, f"---\n_load_conditions:\n{body}---\n\nBody\n")
    ws = tmp_path / "ws"

    with pytest.raises(ValueError, match="tests.md"):
        rules_mod.distribute_rules(source, ws)

    assert not (ws / ".claude").exists()


def test_a_trailing_punctuation_error_says_the_frame_adds_its_own_comma(
    source, tmp_path
):
    _lazy(source, '---\n_load_conditions:\n  - "if you edit,"\n---\n\nBody\n')

    with pytest.raises(ValueError, match="frame adds its own comma") as exc:
        rules_mod.distribute_rules(source, tmp_path / "ws")

    assert "tests.md" in str(exc.value) and "if you edit," in str(exc.value)


def test_a_quoted_item_is_stripped_after_unquoting(source, tmp_path):
    _lazy(source, '---\n_load_conditions:\n  - " x "\n---\n\nBody\n')
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == _stub_text(
        ws, conditions="x"
    )


def test_multi_item_stub_joins_items_with_or(source, tmp_path):
    _lazy(source, "---\n_load_conditions:\n  - A\n  - B\n---\n\nBody\n")
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    content = (ws / ".claude/rules-content/tests.md").resolve()
    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        f"Your FIRST action, A or B, MUST be to `Read` `{content}` in full.\n"
    )


def test_a_blank_item_among_valid_ones_is_refused(source, tmp_path):
    _lazy(source, '---\n_load_conditions:\n  - "if you edit"\n  - ""\n---\n\nBody\n')

    with pytest.raises(ValueError, match="tests.md"):
        rules_mod.distribute_rules(source, tmp_path / "ws")


def test_invalid_condition_error_names_the_condition(source, tmp_path):
    _lazy(source, "---\n_load_conditions:\n  - if you edit `x`\n---\n\nBody\n")

    with pytest.raises(ValueError, match="if you edit `x`"):
        rules_mod.distribute_rules(source, tmp_path / "ws")


def test_lazy_rule_is_idempotent(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    second = rules_mod.distribute_rules(source, ws)

    assert second.unchanged == ["tests.md"]
    assert not second.has_changes


def test_editing_conditions_is_modified_with_new_stub(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    _lazy(source, LAZY_SOURCE.replace("any test", "the CI config"))
    report = rules_mod.distribute_rules(source, ws)

    assert report.modified == ["tests.md"]
    assert "a Python file or the CI config" in (
        ws / ".claude/rules/tests.md"
    ).read_text(encoding="utf-8")


def test_editing_only_the_body_is_modified(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    _lazy(source, LAZY_SOURCE.replace("Body line.", "New line."))
    report = rules_mod.distribute_rules(source, ws)

    assert report.modified == ["tests.md"]
    assert "New line." in (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    )


def test_lazy_becoming_eager_deletes_the_stale_content_file(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)
    (ws / ".claude/rules-content/ghost.md").write_text("x\n", encoding="utf-8")

    _lazy(source, "# Tests\n")
    report = rules_mod.distribute_rules(source, ws)

    assert report == rules_mod.RulesReport(modified=["tests.md"], purged=["ghost.md"])
    assert not (ws / ".claude/rules-content/tests.md").exists()
    assert not (ws / ".claude/rules-content/ghost.md").exists()
    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == "# Tests\n"


def test_lazy_becoming_eager_plan_reports_modified_only(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    _lazy(source, "# Tests\n")
    plan = rules_mod.distribute_rules(source, ws, apply=False)

    assert plan == rules_mod.RulesReport(modified=["tests.md"])
    assert (ws / ".claude/rules-content/tests.md").exists()


def test_eager_becoming_lazy_rewrites_stub_and_creates_content(source, tmp_path):
    _lazy(source, "# Tests\n")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    _lazy(source)
    report = rules_mod.distribute_rules(source, ws)

    assert report == rules_mod.RulesReport(modified=["tests.md"])
    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n---\n\n' + _stub_text(ws)
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY


def test_orphan_in_rules_content_is_purged(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    content = ws / ".claude/rules-content"
    content.mkdir(parents=True)
    (content / "ghost.md").write_text("x\n", encoding="utf-8")

    report = rules_mod.distribute_rules(source, ws)

    assert report == rules_mod.RulesReport(added=["tests.md"], purged=["ghost.md"])
    assert not (content / "ghost.md").exists()
    assert (content / "tests.md").exists()


def test_lazy_plan_writes_nothing(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"

    plan = rules_mod.distribute_rules(source, ws, apply=False)

    assert plan.added == ["tests.md"]
    assert not (ws / ".claude").exists()


def test_distribute_all_plugin_rules_handles_a_lazy_rule(
    tmp_path, monkeypatch, installed_plugins_file
):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-a").mkdir(parents=True)
    (rules_dir / "pc-a" / "tests.md").write_text(LAZY_SOURCE, encoding="utf-8")
    (rules_dir / "pc-b").mkdir()
    (rules_dir / "pc-b" / "other.md").write_text("other\n", encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    installed_plugins_file(
        {"pc-a@m": [{"scope": "user"}], "pc-b@m": [{"scope": "user"}]}
    )
    ws = tmp_path / "workspace"

    result = rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=tmp_path / "u")

    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY
    assert (
        (ws / ".claude/rules/tests.md")
        .read_text(encoding="utf-8")
        .endswith(_stub_text(ws))
    )
    assert result["pc-a"][ws].added == ["tests.md"]
    # the sibling pass must not purge pc-a's content file
    assert result["pc-b"][ws].purged == []
    assert (ws / ".claude/rules-content/tests.md").exists()


def test_withdrawing_a_lazy_rule_removes_its_content_file(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)

    report = rules_mod._withdraw_sources(["tests.md"], ws)

    assert report.purged == ["tests.md"]
    assert not (ws / ".claude/rules/tests.md").exists()
    assert not (ws / ".claude/rules-content/tests.md").exists()


# ── lazy rules: review fixes ──


def test_stub_read_path_is_the_absolute_resolved_content_path(source, tmp_path):
    (source / "x.md").write_text(
        '---\n_load_conditions:\n  - "a file"\n---\n\nB\n', encoding="utf-8"
    )
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    expected = str((ws / ".claude/rules-content/x.md").resolve())
    assert expected in (ws / ".claude/rules/x.md").read_text(encoding="utf-8")
    assert (ws / ".claude/rules/x.md").read_text(encoding="utf-8") == (
        f"Your FIRST action, a file, MUST be to `Read` `{expected}` in full.\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        "---\n_load_conditions:\n  - a file\n\nBody\n",  # fence never closed
        "----\n_load_conditions:\n  - a file\n---\n\nBody\n",  # not a fence
        "---foo\n_load_conditions:\n  - a file\n---\n\nBody\n",  # not a fence
        "---\n_load_conditions:\n  - a file\n----\n\nBody\n",  # closing is not a fence
    ],
)
def test_malformed_frontmatter_is_refused_not_copied_eagerly(source, tmp_path, text):
    _lazy(source, text)
    ws = tmp_path / "ws"

    with pytest.raises(ValueError, match="tests.md: unclosed frontmatter"):
        rules_mod.distribute_rules(source, ws)

    assert not (ws / ".claude").exists()


@pytest.mark.parametrize(
    "text",
    [
        "\ufeff---\npaths:\n  - x\n---\n\nBody\n",  # BOM + valid frontmatter
        "---\n\nBody\n\n---\n",  # a horizontal rule closes the block
        "---\nA horizontal rule opens this file.\n\nBody\n",  # never closed
        "----\nBody\n",  # four dashes
        "---foo\nBody\n",
        "---\npaths:\n  - x\n--- \u00a0x\n\nBody\n",  # closing line is not a fence
        "\ufeff---\nno closing fence\n",
        "\ufeff----\nBody\n",
    ],
)
def test_eager_rule_is_copied_verbatim_whatever_its_first_line(source, tmp_path, text):
    (source / "plain.md").write_text(text, encoding="utf-8", newline="")
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/plain.md").read_bytes() == text.encode("utf-8")
    assert not (ws / ".claude/rules-content").exists()


def test_eager_rule_with_trailing_space_fences_is_copied_verbatim(source, tmp_path):
    text = "--- \t\npaths:\n  - x\n---  \n\nBody\n"
    (source / "plain.md").write_text(text, encoding="utf-8", newline="")
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/plain.md").read_bytes() == text.encode("utf-8")
    assert not (ws / ".claude/rules-content").exists()


def test_one_unparseable_eager_rule_does_not_abort_the_distribution(source, tmp_path):
    (source / "odd.md").write_text("---\nNo closing fence.\n", encoding="utf-8")
    (source / "tests.md").write_text(LAZY_SOURCE, encoding="utf-8")
    ws = tmp_path / "ws"

    report = rules_mod.distribute_rules(source, ws)

    assert report.added == ["odd.md", "tests.md"]
    assert (ws / ".claude/rules/odd.md").read_text(encoding="utf-8") == (
        "---\nNo closing fence.\n"
    )


def test_lazy_rule_with_a_bom_is_distributed(source, tmp_path):
    _lazy(source, "\ufeff" + LAZY_SOURCE)
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n---\n\n' + _stub_text(ws)
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY


def test_lazy_rule_with_trailing_space_fences_is_distributed(source, tmp_path):
    _lazy(source, LAZY_SOURCE.replace("---\n", "---  \t\n"))
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n---\n\n' + _stub_text(ws)
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY


def test_same_line_comment_on_the_key_is_accepted(source, tmp_path):
    _lazy(
        source,
        '---\n_load_conditions:  # note\n  - "a file"\n---\n\nBody\n',
    )
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == _stub_text(
        ws, conditions="a file"
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == "Body\n"


def test_inline_value_with_a_comment_is_still_refused(source, tmp_path):
    _lazy(source, "---\n_load_conditions: a file  # note\n---\n\nBody\n")

    with pytest.raises(ValueError, match="block-style list required"):
        rules_mod.distribute_rules(source, tmp_path / "ws")


@pytest.mark.parametrize(
    "item", ['["a file"]', "a Python file", '["a file", "an IDE setting"]']
)
def test_inline_load_conditions_requires_a_block_list(source, tmp_path, item):
    _lazy(source, f"---\n_load_conditions: {item}\n---\n\nBody\n")

    with pytest.raises(ValueError, match="tests.md.*block-style list required"):
        rules_mod.distribute_rules(source, tmp_path / "ws")


def test_comment_lines_inside_paths_block_do_not_truncate_it(source, tmp_path):
    _lazy(
        source,
        "---\n"
        "paths:\n"
        '  - "**/*.py"\n'
        "# a full-line comment\n"
        "\n"
        "  # an indented comment\n"
        '  - "**/*.toml"\n'
        "_load_conditions:\n"
        '  - "a file"\n'
        "---\n\nBody\n",
    )
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n  - "**/*.toml"\n---\n\n'
        + _stub_text(ws, conditions="a file")
    )


def test_comments_inside_load_conditions_are_skipped_and_stripped(source, tmp_path):
    _lazy(
        source,
        "---\n"
        "_load_conditions:\n"
        '  - "a Python file"  # quoted, noted\n'
        "  # a comment line\n"
        "\n"
        "  - any test # unquoted, noted\n"
        "  - the C# sources\n"
        "---\n\nBody\n",
    )
    ws = tmp_path / "ws"

    rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == _stub_text(
        ws, conditions="a Python file or any test or the C# sources"
    )


def test_missing_content_file_alone_is_modified(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)
    (ws / ".claude/rules-content/tests.md").unlink()

    report = rules_mod.distribute_rules(source, ws)

    assert report == rules_mod.RulesReport(modified=["tests.md"])
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY


def test_missing_stub_alone_is_added(source, tmp_path):
    _lazy(source)
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(source, ws)
    (ws / ".claude/rules/tests.md").unlink()

    report = rules_mod.distribute_rules(source, ws)

    assert report == rules_mod.RulesReport(added=["tests.md"])
    assert (
        (ws / ".claude/rules/tests.md")
        .read_text(encoding="utf-8")
        .endswith(_stub_text(ws))
    )


def test_content_is_written_before_the_stub(source, tmp_path, monkeypatch):
    """A crash while writing the stub must not leave a stub pointing at a missing file."""
    _lazy(source)
    ws = tmp_path / "ws"
    real_write_text = Path.write_text

    def crash_on_stub(self, *args, **kwargs):
        if self.parent.name == "rules":
            raise OSError("disk full")
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", crash_on_stub)

    with pytest.raises(OSError, match="disk full"):
        rules_mod.distribute_rules(source, ws)

    assert (ws / ".claude/rules-content/tests.md").exists()
    assert not (ws / ".claude/rules/tests.md").exists()


def test_sibling_owned_content_file_is_not_purged(tmp_path):
    ws = tmp_path / "ws"
    content = ws / ".claude/rules-content"
    content.mkdir(parents=True)
    (content / "x.md").write_text("body\n", encoding="utf-8")
    (content / "ghost.md").write_text("x\n", encoding="utf-8")

    report = rules_mod._distribute_sources({}, ws, sibling_owned=frozenset({"x.md"}))

    assert report == rules_mod.RulesReport(purged=["ghost.md"])
    assert (content / "x.md").exists()
    assert not (content / "ghost.md").exists()


def _two_plugins_one_lazy(tmp_path, monkeypatch):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-a").mkdir(parents=True)
    (rules_dir / "pc-a" / "a.md").write_text("A\n", encoding="utf-8")
    (rules_dir / "pc-b").mkdir()
    (rules_dir / "pc-b" / "tests.md").write_text(LAZY_SOURCE, encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)


def test_disable_path_protects_a_sibling_plugins_lazy_content(
    tmp_path, monkeypatch, installed_plugins_file
):
    _two_plugins_one_lazy(tmp_path, monkeypatch)
    installed_plugins_file(
        {"pc-a@m": [{"scope": "user"}], "pc-b@m": [{"scope": "user"}]}
    )
    ws = tmp_path / "ws"
    rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=tmp_path / "u")
    ws = ws.resolve()

    reports = rules_mod.rules_report_for_plugin_at_targets(
        "pc-a",
        [],
        [ws],
        ws,
        user_rules_dir=tmp_path / "u",
        active_dirs_by_plugin={"pc-b": [ws]},
    )

    assert reports == {ws: rules_mod.RulesReport(purged=["a.md"])}
    assert not (ws / ".claude/rules/a.md").exists()
    assert (
        (ws / ".claude/rules/tests.md")
        .read_text(encoding="utf-8")
        .endswith(_stub_text(ws))
    )
    assert (ws / ".claude/rules-content/tests.md").read_text(
        encoding="utf-8"
    ) == LAZY_BODY


def test_lazy_rule_in_a_covered_target_is_withdrawn_and_ancestor_stub_is_absolute(
    tmp_path, monkeypatch, installed_plugins_file
):
    rules_dir = tmp_path / "rules"
    (rules_dir / "pc-a").mkdir(parents=True)
    (rules_dir / "pc-a" / "tests.md").write_text(LAZY_SOURCE, encoding="utf-8")
    monkeypatch.setattr(rules_mod, "RULES_DIR", rules_dir)
    ws, group = tmp_path / "ws", tmp_path / "ws" / "group"
    installed_plugins_file(
        {"pc-a@m": [{"scope": "project", "projectPath": str(p)} for p in (ws, group)]}
    )
    (group / ".claude/rules").mkdir(parents=True)
    (group / ".claude/rules-content").mkdir(parents=True)
    (group / ".claude/rules/tests.md").write_text("stale stub\n", encoding="utf-8")
    (group / ".claude/rules-content/tests.md").write_text("stale\n", encoding="utf-8")

    result = rules_mod.distribute_all_plugin_rules(ws, user_rules_dir=tmp_path / "u")

    assert result["pc-a"][group] == rules_mod.RulesReport(purged=["tests.md"])
    assert not (group / ".claude/rules/tests.md").exists()
    assert not (group / ".claude/rules-content/tests.md").exists()
    assert (ws / ".claude/rules/tests.md").read_text(encoding="utf-8") == (
        '---\npaths:\n  - "**/*.py"\n---\n\n' + _stub_text(ws)
    )
