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
    for d in (setup.CORE_DIR / "commands", setup.CORE_DIR / "agents"):
        for f in sorted(d.glob("*.md")):
            assert not patterns.search(f.read_text(encoding="utf-8")), (
                f"{f.name} nomme un artefact d'instance — utiliser le slot, pas l'exemple"
            )


def test_scaffolding_sources_profile_overrides_core_on_name(tmp_path):
    profile_cmds = tmp_path / "commands"
    profile_cmds.mkdir()
    (profile_cmds / "commit.md").write_text("overridden", encoding="utf-8")
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    sources = setup._scaffolding_sources("commands", profile_yaml)
    assert sources["commit.md"] == profile_cmds / "commit.md"


def test_scaffolding_sources_rules_layers_base_and_profile(tmp_path):
    # Les rules privées du profil (ex. pinky-libs, qui nomme des libs produit) SONT layerées sur la
    # base publique — même split public/privé que commands/agents (cf. docstring _scaffolding_sources).
    profile_rules = tmp_path / "rules"
    profile_rules.mkdir()
    (profile_rules / "private-rule.md").write_text(
        "instance-specific", encoding="utf-8"
    )
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    sources = setup._scaffolding_sources("rules", profile_yaml, scope_caps=frozenset())
    assert sources["private-rule.md"] == profile_rules / "private-rule.md"
    # Périmètre sans capacité → il ne reste que la base : aucune règle de domaine ne passe.
    base = setup.CORE_DIR / "rules" / "base"
    others = {n: p for n, p in sources.items() if n != "private-rule.md"}
    assert others and all(p.is_relative_to(base) for p in others.values())


def test_domain_rules_join_the_same_rule_set_when_the_capability_is_in_scope(tmp_path):
    """ADR-0060 — la capacité décide la PRÉSENCE d'une règle de domaine, `paths:` son CHARGEMENT.

    Remplace le domain layer d'ADR-0014, qui rendait ses règles dans `WORKSPACE_ROOT/<subdir>/` en
    supposant que les repos y seraient clonés. Ils ne l'ont jamais été — `discover_repos()` globe la
    RACINE — donc ces 6 règles n'ont jamais atteint une session. Vérifié le 2026-08-05 : zéro
    intersection entre `<workspace>/.claude/rules/` et `pinky/.claude/rules/`.
    """
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    sans = setup._scaffolding_sources("rules", profile_yaml, scope_caps=frozenset())
    avec = setup._scaffolding_sources(
        "rules", profile_yaml, scope_caps=frozenset({"snowflake"})
    )
    domain = {
        f.name for f in (setup.CORE_DIR / "rules" / "domain-snowflake").glob("*.md")
    }

    assert domain, "le répertoire domain-snowflake ne doit pas être vide"
    assert domain.isdisjoint(sans)  # hors périmètre : aucune
    assert domain.issubset(set(avec))  # dans le périmètre : toutes
    assert set(avec) - set(sans) == domain  # oracle : elles seules changent


def test_every_domain_rule_is_path_scoped(tmp_path):
    """Une règle de domaine DOIT porter `paths:` — sinon elle coûte du contexte à chaque session.

    Elle vit désormais dans le `.claude/rules/` de la racine, partagé par tous les repos frères ;
    sans `paths:` elle serait injectée même en travaillant sur un repo JS. C'est précisément la
    dépense qu'ADR-0057 a mesurée et réduite, et le prix à payer pour avoir supprimé le sous-arbre.
    """
    for f in sorted((setup.CORE_DIR / "rules" / "domain-snowflake").glob("*.md")):
        head = f.read_text(encoding="utf-8").split("---")[1]
        assert "paths:" in head, f"{f.name} n'est pas scopée par paths:"
        assert "capability:" in head, f"{f.name} ne déclare pas sa capacité"


def test_scaffolding_sources_no_profile_is_core_only():
    sources = setup._scaffolding_sources("commands", None)
    assert all(p.is_relative_to(setup.CORE_DIR) for p in sources.values())


# --- Routage par capacité : `capability:` (le repo) + `machine:` (l'opérateur) -------------------
#
# Remplace la clé `commands:` du profil (2026-07-31 → 2026-08-05). Elle faisait dépendre la réponse
# du PROFIL sélectionné sur la machine ; l'exigence voyage maintenant avec la commande elle-même.

# Les commandes de core/ qui portent une exigence. Tout le reste est socle. Ce set EST l'oracle des
# tests ci-dessous : un tag oublié ou de trop le fait tomber, ce qu'un `in` ne verrait pas.
TAGGED_CORE_COMMANDS = {
    "snowpark_to_sql.md",
    "sql_to_snowpark.md",
    "code_comments.md",
    "yml_audit.md",  # elles portent capability: snowflake depuis le lot 1
    "release.md",
    "cortex_integrate.md",
    "local.md",
}


def test_chantier_is_socle_and_must_stay_so():
    """`/chantier` ne porte AUCUNE exigence — jamais.

    C'est la feature principale du workspace (le kanban agent-maintenu en est le différenciateur),
    donc elle doit atterrir sur toute machine, board ou pas. Sans board elle ne casse pas : elle n'a
    rien à afficher, ce qui est une DÉGRADATION et non une exigence — exactement la distinction que
    ce lot pose (« on tague une exigence, jamais une option »).

    Ce test existe parce que la règle a déjà été enfreinte une fois : `machine: kanban` avait été
    posé le 2026-08-05 sur la foi d'un commentaire de profil périmé (« à rajouter dès qu'un kanban
    partagé existe »), alors que le board partagé existait depuis le 2026-07-31. Un commentaire ne
    garde rien ; ce test, si.
    """
    chantier = setup.CORE_DIR / "commands" / "chantier.md"
    assert setup.profile._command_requirements(chantier) == (None, None)
    assert setup.profile._meets_requirements(chantier, frozenset())


def test_command_without_requirement_is_socle(tmp_path):
    # Défaut volontairement permissif : oublier une clé rend une commande PLUS disponible, jamais
    # silencieusement absente. Une commande qui disparaît sans raison est bien plus dure à
    # diagnostiquer qu'une commande inutile qui traîne.
    cmd = tmp_path / "plain.md"
    cmd.write_text("---\ndescription: nothing special\n---\n", encoding="utf-8")

    assert setup.profile._command_requirements(cmd) == (None, None)
    assert setup.profile._meets_requirements(cmd, frozenset())


def test_command_requirements_are_read_from_the_frontmatter_only(tmp_path):
    # Le corps ne doit RIEN déclarer : une ligne « capability: snowflake » dans la prose d'une
    # commande est de la documentation, pas une exigence.
    cmd = tmp_path / "tagged.md"
    cmd.write_text(
        "---\ndescription: d\ncapability: snowflake\nmachine: cortex\n---\n"
        "\n# Corps\n\ncapability: web\n",
        encoding="utf-8",
    )

    assert setup.profile._command_requirements(cmd) == ("snowflake", "cortex")


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
    assert "capability:" in out and "machine:" in out  # le message dit quoi faire


def test_resolve_scope_capabilities_single_repo_vs_machine_union(tmp_path):
    # Les deux périmètres d'installation. `--into` vise UN repo → routage exact ; le mode workspace
    # n'a qu'un .claude/ pour N repos → union, seule réponse disponible (cf. la docstring).
    lib = tmp_path / "a_lib"
    (lib / "src").mkdir(parents=True)
    (lib / "pyproject.toml").write_text(
        '[project]\nname = "a"\ndependencies = ["snowflake"]\n', encoding="utf-8"
    )
    plain = tmp_path / "a_site"
    plain.mkdir()
    (plain / "package.json").write_text("{}", encoding="utf-8")

    assert setup.resolve_scope_capabilities(lib) == frozenset({"python", "snowflake"})
    assert setup.resolve_scope_capabilities(plain) == frozenset({"web"})


# --- Agents de connaissance routés par capacité (ADR-0058) --------------------------------------


def test_frontmatter_is_only_read_when_the_file_opens_with_it(tmp_path):
    """Un `---` dans le CORPS n'ouvre pas un frontmatter.

    Bug latent introduit au lot 1 et corrigé ici : le parseur traitait le premier `---` rencontré
    comme une ouverture, donc sur un fichier sans frontmatter il scannait le corps. Or `---` est du
    markdown ordinaire (filet horizontal, séparation de section) et les agents en sont pleins —
    l'agent aurait hérité d'une capacité écrite dans sa prose.
    """
    # La ligne piège est AVANT tout `---` du corps : sinon un parseur laxiste s'arrêterait dessus
    # et le test passerait pour la mauvaise raison (vérifié par mutation le 2026-08-05 — la première
    # version de ce test ne discriminait rien).
    piege = tmp_path / "AGENT_PIEGE.md"
    piege.write_text(
        "# AGENT_PIEGE.md — sans frontmatter\n"
        "*Update date : 2026-01-01 10:00*\n\n"
        "> Cet agent explique la clé `capability:` de ses voisins.\n"
        "capability: snowflake\n\n"
        "---\n\n## Section\n",
        encoding="utf-8",
    )
    assert setup.profile._frontmatter_field(piege, "capability") is None

    vrai = tmp_path / "AGENT_VRAI.md"
    vrai.write_text(
        "---\ncapability: snowflake\n---\n# AGENT_VRAI.md\n", encoding="utf-8"
    )
    assert setup.profile._frontmatter_field(vrai, "capability") == "snowflake"

