"""Public-corpus hygiene — the moteur's own commands/agents/rules never leak instance-specific
content, and every domain rule stays path-scoped (chantier-0001 card `agents-commands-layering`).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


def test_no_public_artefact_names_a_private_instance():
    """Le garde-fou qui rend le retour au public SÛR, et pas seulement possible.

    C'est la propriété qui manquait : rien ne vérifiait qu'un fichier public ne nomme pas un artefact
    d'instance. Le leak guard le fait au commit ; ce test le fait à l'endroit où la régression
    naîtrait — quelqu'un remet un exemple concret « pour que ce soit plus clair ».
    """
    import re as _re

    patterns = _re.compile(r"agent_pinky|agent_snowflake_pinky|pythia", _re.I)
    for d in (
        setup.AGENTIC_HARNESS_DIR / "commands",
        setup.AGENTIC_HARNESS_DIR / "agents",
    ):
        for f in sorted(d.glob("*.md")):
            assert not patterns.search(f.read_text(encoding="utf-8")), (
                f"{f.name} nomme un artefact d'instance — utiliser le slot, pas l'exemple"
            )


def test_every_domain_rule_is_path_scoped(tmp_path):
    """Une règle de domaine DOIT porter `paths:` — sinon elle coûte du contexte à chaque session.

    Elle vit désormais dans le `.claude/rules/` de la racine, partagé par tous les repos frères ;
    sans `paths:` elle serait injectée même en travaillant sur un repo JS. C'est précisément la
    dépense qu'ADR-0057 a mesurée et réduite, et le prix à payer pour avoir supprimé le sous-arbre.
    """
    for f in sorted(
        (setup.AGENTIC_HARNESS_DIR / "rules" / "domain-snowflake").glob("*.md")
    ):
        head = f.read_text(encoding="utf-8").split("---")[1]
        assert "paths:" in head, f"{f.name} n'est pas scopée par paths:"
        assert "capability:" in head, f"{f.name} ne déclare pas sa capacité"
