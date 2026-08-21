"""`pinky install` ne nomme aucun repo ni aucune org codés en dur.

Trouvé le 2026-08-09 en rejouant l'install d'un tiers de bout en bout : la commande imprimait
`git clone git@github.com:<PINKY_ORG>/pinky-core` à CHAQUE rendu. Sur une machine d'une autre org,
elle nommait les repos privés d'une org que cet opérateur ne connaît pas — et `<PINKY_ORG>` n'était
jamais substitué, donc le message n'était même pas utilisable par l'auteure.

Un test et pas seulement un fix : le littéral d'instance dans le moteur est une classe de défaut que
trois ADR combattent (0065, 0068, 0069) et qui revient par la sortie console, une surface qu'aucun
autre contrôle ne regarde.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ROOT = Path(__file__).parent.parent
CLI = ROOT / "setup" / "cli.py"

# Noms d'org et de repos produit : ce que le moteur ne doit pas connaître. Le mot « pinky » seul est
# légitime (c'est le nom de l'outil, il est partout) — ce qui ne l'est pas, c'est un repo ou une org
# NOMMÉE, donc le motif exige la forme.
FORBIDDEN = re.compile(
    r"pinky-(?:core|tools|studio|provider|snowpark|connect|streamlit|airflow|ai)\b"
    r"|<PINKY_ORG>"
    r"|github\.com[:/]pinky-and-co",
)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Lignes hors commentaire pur — un commentaire peut citer le littéral qu'il explique."""
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        out.append((i, line))
    return out


def test_the_cli_prints_no_hardcoded_repo_or_org_name():
    hits = [
        f"{CLI.name}:{i}: {ln.strip()}"
        for i, ln in _code_lines(CLI)
        if FORBIDDEN.search(ln)
    ]

    assert not hits, (
        "littéral d'instance dans la sortie du CLI :\n  " + "\n  ".join(hits) + "\n"
        "→ Dériver du workspace (`discover_repos()`), jamais nommer un repo ou une org."
    )


def test_the_pattern_would_actually_catch_the_regression():
    """Anti-tautologie : le motif doit reconnaître la ligne exacte qui a été supprimée."""
    assert FORBIDDEN.search(
        '    print("  git clone git@github.com:<PINKY_ORG>/pinky-core")'
    )
    assert not FORBIDDEN.search('    print(f"Repos matching `{globs}`: {len(found)}")')


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
