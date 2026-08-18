"""Distribution des rules — `rules/core/` → `<workspace>/.claude/rules/`.

Le comportement verrouillé ici est celui de la **transition** : la migration déplace les rules une
par une, donc une rule encore absente de `rules/core/` doit survivre à une distribution. Une purge
prématurée effacerait les 19 rules pas encore migrées, dans un répertoire qui n'est sous aucun git
— irrécupérable. Le jour où la purge deviendra le comportement voulu, c'est ce fichier qui devra
être réécrit en connaissance de cause, pas contourné.
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
    """Une rule est écrite au premier passage, inchangée au second."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"

    first = rules_mod.distribute_rules(ws)
    assert first.written == ["workflow.md"]
    assert first.unchanged == []
    assert (ws / ".claude/rules/workflow.md").read_text(
        encoding="utf-8"
    ) == "# Workflow\n"

    second = rules_mod.distribute_rules(ws)
    assert second.written == []
    assert second.unchanged == ["workflow.md"]


def test_source_change_is_pushed(source: Path, tmp_path: Path) -> None:
    """Une source modifiée réécrit la cible."""
    (source / "workflow.md").write_text("v1\n", encoding="utf-8")
    ws = tmp_path / "ws"
    rules_mod.distribute_rules(ws)

    (source / "workflow.md").write_text("v2\n", encoding="utf-8")
    report = rules_mod.distribute_rules(ws)

    assert report.written == ["workflow.md"]
    assert (ws / ".claude/rules/workflow.md").read_text(encoding="utf-8") == "v2\n"


def test_orphan_is_reported_and_never_deleted(source: Path, tmp_path: Path) -> None:
    """Une rule pas encore migrée survit à la distribution — LE point de la transition."""
    (source / "workflow.md").write_text("# Workflow\n", encoding="utf-8")
    ws = tmp_path / "ws"
    target = ws / ".claude/rules"
    target.mkdir(parents=True)
    (target / "kanban.md").write_text("pas encore migrée\n", encoding="utf-8")

    report = rules_mod.distribute_rules(ws)

    assert report.orphans == ["kanban.md"], "l'orpheline doit être signalée"
    assert (target / "kanban.md").exists(), (
        "une orpheline ne doit JAMAIS être supprimée"
    )
    assert (target / "kanban.md").read_text(encoding="utf-8") == "pas encore migrée\n"


def test_missing_source_dir_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Une source absente lève, au lieu de rapporter une distribution vide réussie."""
    monkeypatch.setattr(rules_mod, "CORE_RULES_DIR", tmp_path / "nowhere")
    with pytest.raises(FileNotFoundError):
        rules_mod.distribute_rules(tmp_path / "ws")
