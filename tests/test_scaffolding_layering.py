"""Scaffolding layering — public core/ commands+agents + the active profile's private set.

Defines "done" for the chantier-0001 card `agents-commands-layering`: a leaky/instance-specific
command (review_brief, explain, yml_audit) or agent (yaml-audit) lives in the PRIVATE corpus, not
in the public moteur. setup.py layers `core/<sub>/` (public) with `<profile dir>/<sub>/` (private),
profile file overriding a core file of the same name; `rules` stays base-only.
"""

import sys
from pathlib import Path

import pytest

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


# Deux tests ont été retirés d'ici : ils exigeaient `core/rules/base/` et
# `core/rules/domain-snowflake/` non vides. Ces répertoires n'ont jamais été portés dans ce repo,
# et le découpage qui les remplace est `rules/core/` + `rules/<plugin>/` — ils n'avaient donc plus
# d'objet, tout en bloquant chaque commit du repo via les hooks. La distribution des rules est
# désormais couverte par `test_rules_distribution.py`.


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


def test_commands_key_is_now_a_build_error(tmp_path, capsys):
    # La clé supprimée ne doit pas être ignorée en silence : un profil qui la porte encore aurait
    # l'air de gouverner quelque chose sans aucun effet, et l'auteur ne le découvrirait que des mois
    # plus tard en s'étonnant d'une commande inattendue.
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")
    profile = {
        "name": "x",
        "knowledge_agents": [],
        "model_routing": {"fast": "f", "default": "d", "thorough": "t"},
        "commands": ["commit"],
    }
    with pytest.raises(SystemExit):
        setup.validate_profile(profile, profile_yaml)
    out = capsys.readouterr().out
    assert "commands: key removed" in out
