"""Distribution des rules — `rules/core/` → `<workspace>/.claude/rules/`.

La migration des rules est terminée (2026-08-20) : la cible est un miroir strict de `rules/core/`,
un fichier sans source correspondante y est de la dérive et doit être purgé.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from setup import rules as rules_mod


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige `rules/core/` du repo vers un répertoire jetable.

    Args:
        tmp_path: Répertoire temporaire fourni par pytest.
        monkeypatch: Fixture de patch pytest.

    Returns:
        Le répertoire source jetable, déjà créé.
    """
    src = tmp_path / "src_rules"
    src.mkdir()
    monkeypatch.setattr(rules_mod, "CORE_RULES_DIR", src)
    return src


def test_distributes_and_is_idempotent(source: Path, tmp_path: Path) -> None:
    """Une rule est ajoutée au premier passage, inchangée au second."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"

    first = rules_mod.distribute_rules(ws)
    assert first.added == ["workflow.md"]
    assert first.modified == []
    assert first.unchanged == []
    assert (ws / ".claude/rules/workflow.md").read_text(
        encoding="utf-8"
    ) == "# Workflow\n"

    second = rules_mod.distribute_rules(ws)
    assert second.added == []
    assert second.modified == []
    assert second.unchanged == ["workflow.md"]


def test_source_change_is_pushed(source: Path, tmp_path: Path) -> None:
    """Une source modifiée réécrit la cible, et compte comme une modification, pas un ajout."""
    (source / "workflow.md").write_text("v1\n", encoding="utf-8")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(ws)

    (source / "workflow.md").write_text("v2\n", encoding="utf-8")
    report = rules_mod.distribute_rules(ws)

    assert report.modified == ["workflow.md"]
    assert report.added == []
    assert (ws / ".claude/rules/workflow.md").read_text(encoding="utf-8") == "v2\n"


def test_plan_does_not_touch_the_filesystem(source: Path, tmp_path: Path) -> None:
    """`apply=False` calcule le même diff mais n'écrit, ne crée ni ne supprime rien."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"

    plan = rules_mod.distribute_rules(ws, apply=False)

    assert plan.added == ["workflow.md"]
    assert plan.has_changes
    assert not (ws / ".claude/rules").exists(), (
        "un plan ne doit même pas créer le répertoire cible"
    )

    applied = rules_mod.distribute_rules(ws, apply=True)
    assert applied.added == ["workflow.md"]
    assert (ws / ".claude/rules/workflow.md").exists()


def test_orphan_is_purged(source: Path, tmp_path: Path) -> None:
    """Un fichier cible sans source correspondante dans rules/core/ est supprimé et rapporté."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("plus de source\n", encoding="utf-8")

    report = rules_mod.distribute_rules(ws)

    assert report.purged == ["stale.md"], "l'orpheline doit être signalée comme purgée"
    assert not (target / "stale.md").exists(), "une orpheline doit être supprimée"


def test_purge_plan_does_not_delete(source: Path, tmp_path: Path) -> None:
    """`apply=False` liste une orpheline sans la supprimer."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("plus de source\n", encoding="utf-8")

    plan = rules_mod.distribute_rules(ws, apply=False)

    assert plan.purged == ["stale.md"]
    assert (target / "stale.md").exists(), "un plan ne supprime rien"


def test_no_changes_reports_no_changes(source: Path, tmp_path: Path) -> None:
    """Une distribution déjà à jour ne rapporte aucun changement."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(ws)

    report = rules_mod.distribute_rules(ws, apply=False)

    assert not report.has_changes
    assert report.unchanged == ["workflow.md"]


def test_missing_source_dir_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une source absente lève, au lieu de rapporter une distribution vide réussie."""
    monkeypatch.setattr(rules_mod, "CORE_RULES_DIR", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError):
        rules_mod.distribute_rules(tmp_path / "ws")
