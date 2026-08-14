"""Cliquet — tout ADR du moteur a sa ligne dans `docs/index.md`.

Card `docs-index-rate-sept-adr` : 0058 à 0064 (sept d'affilée) manquaient de `docs/index.md`, cassés
entre le 2026-08-05 et le 2026-08-07 malgré une convention écrite (`doc_conventions.md`: « Add a
pointer to docs/index.md when creating a new ADR ») lue à chaque session. La convention respectée 57
fois puis ratée 7 fois n'était pas un oubli : elle dépend d'une relecture humaine/session, qui ne se
déclenche pas de façon fiable à l'écriture d'un fichier (une règle scopée `paths:` s'injecte à la
*lecture* d'un fichier qui matche, jamais à l'écriture seule — ADR-0057). Même doctrine que
`test_config_surface_documented.py` : la liste attendue est **dérivée du disque**, jamais recopiée
ici, et le cliquet passe par le gate de test bloquant universel (ADR-0056) plutôt que de compter sur
la vigilance de session.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
ADR_DIR = ROOT / "docs" / "adr"
INDEX = ROOT / "docs" / "index.md"


def adrs_on_disk() -> set[str]:
    return {p.name for p in ADR_DIR.glob("*.md")}


def test_every_adr_is_listed_in_the_index():
    text = INDEX.read_text(encoding="utf-8")
    missing = sorted(name for name in adrs_on_disk() if f"adr/{name}" not in text)

    assert not missing, (
        f"ADR présent(s) sur disque et absent(s) de {INDEX.name} : {', '.join(missing)}.\n"
        "→ Ajouter une ligne `- [adr/<fichier>](adr/<fichier>) — <résumé>` (doc_conventions.md)."
    )


def test_the_extraction_itself_is_not_silently_empty():
    """Un cliquet dont la source se tarit passe au vert en ne surveillant plus rien."""
    found = adrs_on_disk()
    assert len(found) >= 60, f"seulement {len(found)} ADR trouvés — extraction suspecte"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
