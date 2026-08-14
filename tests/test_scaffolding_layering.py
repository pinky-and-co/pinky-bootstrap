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


def test_generic_craft_lives_in_the_public_core():
    """Renversement assumé de la décision `agents-commands-layering` (2026-08-06).

    Ces quatre artefacts avaient été relogés dans le corpus PRIVÉ au motif qu'ils étaient
    « leaky/instance-specific ». Mesuré : ils ne contiennent **aucun** leak_pattern. `review_brief`
    en particulier — 431 lignes — n'était bloqué que par **un mot**, l'exemple
    `AGENT_<INSTANCE>_REVIEW_CONVENTIONS.md` de son étape 2b, qui matchait le pattern `agent_pinky`.
    Six semaines d'allers-retours public↔privé pour cet exemple.

    L'exemple a disparu avec le passage au slot déclaré (`slot: review`) : une commande publique ne
    nomme plus jamais le fichier d'une instance, elle nomme le SLOT et le moteur résout qui le
    remplit. D'où le retour au public, définitif cette fois.
    """
    core_cmds = {f.name for f in (setup.CORE_DIR / "commands").glob("*.md")}
    core_agents = {f.name for f in (setup.CORE_DIR / "agents").glob("*.md")}
    assert {"review_brief.md", "explain.md", "yml_audit.md"} <= core_cmds
    assert "yaml-audit.md" in core_agents


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


def test_scaffolding_sources_commands_layers_core_and_profile(tmp_path):
    (setup.CORE_DIR / "commands")  # core dir exists in the repo
    profile_cmds = tmp_path / "commands"
    profile_cmds.mkdir()
    (profile_cmds / "review_brief.md").write_text("private brief", encoding="utf-8")
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    sources = setup._scaffolding_sources("commands", profile_yaml)
    # public core command still present...
    assert "careful.md" in sources
    assert sources["careful.md"].is_relative_to(setup.CORE_DIR)
    # ...and the profile's private command is layered in
    assert "review_brief.md" in sources
    assert sources["review_brief.md"] == profile_cmds / "review_brief.md"


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


def test_scope_without_capabilities_drops_exactly_the_tagged_commands(
    tmp_path, monkeypatch
):
    # Oracle d'égalité sur la DIFFÉRENCE : c'est l'état d'une machine tierce (aucune capacité de
    # repo, aucun outil déclaré) — la cible #2 du chantier 0001. Assertion stable dans le temps :
    # elle se dérive des tags, donc un mauvais tag la fait tomber.
    # `explain.md` n'est PAS dans TAGGED_CORE_COMMANDS : sa propre doc promet un mode dégradé
    # générique pour une machine sans capacité (§ Convention reference), donc `capability: snowflake`
    # dessus contredisait le comportement documenté — retiré le 2026-08-07 (squelettes-publics-manquants).
    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset())
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    everything = set(
        setup._scaffolding_sources("commands", profile_yaml, filtered=False)
    )
    kept = set(
        setup._scaffolding_sources("commands", profile_yaml, scope_caps=frozenset())
    )
    assert everything - kept == TAGGED_CORE_COMMANDS
    assert "careful.md" in kept  # le socle survit toujours


def test_capability_command_returns_when_the_scope_provides_it(tmp_path, monkeypatch):
    # Preuve par mutation dans l'autre sens : c'est bien la capacité qui pilote, pas un hasard.
    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset())
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")

    without = setup._scaffolding_sources(
        "commands", profile_yaml, scope_caps=frozenset()
    )
    with_sf = setup._scaffolding_sources(
        "commands", profile_yaml, scope_caps=frozenset({"snowflake"})
    )
    assert set(with_sf) - set(without) == {
        "snowpark_to_sql.md",
        "sql_to_snowpark.md",
        "code_comments.md",
        "yml_audit.md",
    }
    # Aucune capacité de repo ne débloque une exigence MACHINE — les deux axes sont disjoints.
    # `release` en est le cas mesuré : taguer `capability: python` l'aurait fait atterrir sur un
    # poste POC (pluto-poc-pilot a un pyproject.toml), alors que publier sur PyPI est une propriété
    # de l'opérateur, pas du repo. D'où `machine: pypi`.
    assert "release.md" not in with_sf


def test_machine_command_needs_the_machine_declaration(tmp_path, monkeypatch):
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")
    full = frozenset({"snowflake", "python", "web", "python-lint"})

    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset())
    assert "cortex_integrate.md" not in setup._scaffolding_sources(
        "commands", profile_yaml, scope_caps=full
    )
    # Aucune capacité de REPO ne peut débloquer une exigence machine — les deux axes sont disjoints.
    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset({"cortex"}))
    kept = setup._scaffolding_sources("commands", profile_yaml, scope_caps=full)
    assert "cortex_integrate.md" in kept
    assert "local.md" not in kept  # exige local-model, non déclaré


def test_commands_index_is_pinned_end_to_end(tmp_path, monkeypatch):
    """Oracle d'égalité sur la sortie ENTIÈRE (tests.md § generator oracle).

    `build_commands_index` est un générateur : une assertion par fragment passerait aussi bien sur la
    bonne table que sur une table mal filtrée, mal ordonnée ou mal formatée. On rend donc la sortie
    déterministe en contrôlant `CORE_DIR` — impossible autrement, le vrai core/ grossit — ce qui
    épingle d'un coup l'en-tête, le gabarit de ligne, l'ORDRE et le filtrage par capacité.
    """
    core = tmp_path / "core"
    (core / "commands").mkdir(parents=True)
    (core / "commands" / "alpha.md").write_text(
        "---\ndescription: does alpha\n---\n", encoding="utf-8"
    )
    (core / "commands" / "zeta.md").write_text(
        "---\ndescription: does zeta\ncapability: snowflake\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(setup.profile, "CORE_DIR", core)
    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset())

    assert setup.build_commands_index(None, frozenset()) == (
        "| Command | What it does |\n"
        "|---------|-------------|\n"
        "| `/alpha` | does alpha |"
    )
    # Même oracle, capacité présente : la ligne apparaît, à sa place dans l'ordre trié.
    assert setup.build_commands_index(None, frozenset({"snowflake"})) == (
        "| Command | What it does |\n"
        "|---------|-------------|\n"
        "| `/alpha` | does alpha |\n"
        "| `/zeta` | does zeta |"
    )


def test_rendered_index_agrees_with_the_installed_set(tmp_path, monkeypatch):
    # Les deux consommateurs doivent rester d'accord : les fichiers copiés dans .claude/commands/ +
    # .claude/skills/ ET la table du CLAUDE.md. Une table qui annonce une commande ou une skill
    # absente de la machine est la dérive que build_commands_index existe pour tuer. Une skill crée
    # aussi une commande slash (2026-08-09, migration `commit`) — l'index couvre les deux sources.
    import re

    monkeypatch.setattr(setup.profile, "MACHINE_CAPABILITIES", frozenset())
    profile_yaml = tmp_path / "profile.yaml"
    profile_yaml.write_text("name: x", encoding="utf-8")
    caps = frozenset({"snowflake"})

    sources = setup._scaffolding_sources("commands", profile_yaml, scope_caps=caps)
    skills = setup._skill_sources(profile_yaml)
    invocable_skills = {
        name
        for name, skill_dir in skills.items()
        if setup.profile._frontmatter_field(skill_dir / "SKILL.md", "user-invocable")
        != "false"
    }
    index = setup.build_commands_index(profile_yaml, caps)
    listed = set(re.findall(r"^\| `/([a-z_0-9-]+)` \|", index, re.M))
    assert listed == {Path(n).stem for n in sources} | invocable_skills

    # Oracle de format sur une ligne entière : l'en-tête et le gabarit de ligne sont épinglés, pas
    # seulement la présence du nom.
    assert (
        "| `/snowpark_to_sql` | Translate Snowpark Python (DataFrame API) into the "
        "equivalent Snowflake SQL, preferring Snowpark's own generated SQL as the "
        "oracle when executable |"
    ) in index
    assert "`/cortex_integrate`" not in index  # exigence machine non satisfaite


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


def test_discovery_keeps_socle_agents_and_filters_the_rest(tmp_path, monkeypatch):
    # Oracle d'égalité sur l'ensemble : un `in` passerait aussi sur un filtre qui ne filtre rien.
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "AGENT_SOCLE.md").write_text("# AGENT_SOCLE.md\n", encoding="utf-8")
    (kdir / "AGENT_SF.md").write_text(
        "---\ncapability: snowflake\n---\n# AGENT_SF.md\n", encoding="utf-8"
    )
    (kdir / "AGENT_WEB.md").write_text(
        "---\ncapability: web\n---\n# AGENT_WEB.md\n", encoding="utf-8"
    )
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [tmp_path])

    assert set(setup.profile._discover_capability_agents(frozenset())) == {
        "AGENT_SOCLE.md"
    }
    assert set(setup.profile._discover_capability_agents(frozenset({"snowflake"}))) == {
        "AGENT_SOCLE.md",
        "AGENT_SF.md",
    }
    assert set(
        setup.profile._discover_capability_agents(frozenset({"snowflake", "web"}))
    ) == {"AGENT_SOCLE.md", "AGENT_SF.md", "AGENT_WEB.md"}


def test_discovery_serves_every_declared_roots_profile_corpus(tmp_path, monkeypatch):
    """Déclarer une racine de corpus = souscrire à son savoir, corpus privés de profils compris.

    Avant (ADR-0058), seul `<racine>/knowledge/` était scanné : une racine dont TOUT le savoir vit
    sous `profiles/<nom>/knowledge/` était déclarée et ne produisait rien. Défaut silencieux — rien
    n'échoue, il manque juste des agents que personne ne sait devoir attendre (mesuré le 2026-08-08 :
    4 agents d'un corpus monté, jamais servis).

    Oracle d'égalité sur l'ensemble : un `in` passerait aussi sur une découverte qui ne découvre
    qu'une moitié. Le filtre par capacité s'applique aux deux niveaux, sans exception — un agent
    privé n'échappe pas au routage parce qu'il est privé.
    """
    root = tmp_path / "corpus"
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge" / "AGENT_PUBLIC.md").write_text("# Pub\n", encoding="utf-8")
    for profil, agent, front in (
        ("alpha", "AGENT_ALPHA_SOCLE.md", ""),
        ("alpha", "AGENT_ALPHA_WEB.md", "---\ncapability: web\n---\n"),
        ("beta", "AGENT_BETA_SOCLE.md", ""),
    ):
        kdir = root / "profiles" / profil / "knowledge"
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / agent).write_text(f"{front}# {agent}\n", encoding="utf-8")
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [root])

    assert set(setup.profile._discover_capability_agents(frozenset())) == {
        "AGENT_PUBLIC.md",
        "AGENT_ALPHA_SOCLE.md",
        "AGENT_BETA_SOCLE.md",
    }
    assert set(setup.profile._discover_capability_agents(frozenset({"web"}))) == {
        "AGENT_PUBLIC.md",
        "AGENT_ALPHA_SOCLE.md",
        "AGENT_ALPHA_WEB.md",
        "AGENT_BETA_SOCLE.md",
    }


def test_public_knowledge_wins_over_a_private_homonym(tmp_path, monkeypatch):
    """Deux agents homonymes ne coexistent pas (indexation par nom de fichier) — le public gagne.

    L'inverse ferait qu'un corpus privé monté ÉCLIPSE silencieusement un agent du socle pour tout
    le monde. Précédence explicite plutôt qu'ordre de parcours : c'est un choix, pas un effet de
    bord. Le `knowledge_agents:` du profil actif reste au-dessus des deux (il écrase après coup).
    """
    root = tmp_path / "corpus"
    (root / "knowledge").mkdir(parents=True)
    (root / "knowledge" / "AGENT_DUP.md").write_text("# Public\n", encoding="utf-8")
    priv = root / "profiles" / "alpha" / "knowledge"
    priv.mkdir(parents=True)
    (priv / "AGENT_DUP.md").write_text("# Privé\n", encoding="utf-8")
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [root])

    found = setup.profile._discover_capability_agents(frozenset())
    assert found == {"AGENT_DUP.md": root / "knowledge" / "AGENT_DUP.md"}


def test_profile_declared_agent_is_filtered_too(tmp_path, monkeypatch):
    """Un agent PRIVÉ listé par le profil est soumis au même filtre que les publics.

    Sinon un profil contournerait le routage en listant à la main — précisément ce que la clé
    `commands:` faisait, et qu'on a supprimée au lot 1.
    """
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [])
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "AGENT_PRIVE_SF.md").write_text(
        "---\ncapability: snowflake\n---\n# AGENT_PRIVE_SF.md\n", encoding="utf-8"
    )
    (kdir / "AGENT_PRIVE_ORG.md").write_text("# AGENT_PRIVE_ORG.md\n", encoding="utf-8")
    profile = {
        "knowledge_agents": [
            "knowledge/AGENT_PRIVE_SF.md",
            "knowledge/AGENT_PRIVE_ORG.md",
        ],
        "knowledge_roots": [],
    }
    pp = tmp_path / "profile.yaml"

    sans, _ = setup.profile.resolve_profile_agents(profile, pp, frozenset())
    avec, _ = setup.profile.resolve_profile_agents(
        profile, pp, frozenset({"snowflake"})
    )
    assert set(sans) == {"AGENT_PRIVE_ORG.md"}
    assert set(avec) == {"AGENT_PRIVE_ORG.md", "AGENT_PRIVE_SF.md"}


def test_index_order_is_discovered_then_declared(tmp_path, monkeypatch):
    """L'ordre de déclaration du profil reste la lecture voulue, pour la moitié qu'il contrôle."""
    pub = tmp_path / "pub" / "knowledge"
    pub.mkdir(parents=True)
    (pub / "AGENT_BETA.md").write_text("# Beta\n", encoding="utf-8")
    (pub / "AGENT_ALPHA.md").write_text("# Alpha\n", encoding="utf-8")
    priv = tmp_path / "knowledge"
    priv.mkdir()
    (priv / "AGENT_ZULU.md").write_text("# Zulu\n", encoding="utf-8")
    (priv / "AGENT_MIKE.md").write_text("# Mike\n", encoding="utf-8")
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [tmp_path / "pub"])
    profile = {
        "knowledge_agents": ["knowledge/AGENT_ZULU.md", "knowledge/AGENT_MIKE.md"],
        "knowledge_roots": [],
    }

    index = setup.build_knowledge_index(
        profile,
        tmp_path / "profile.yaml",
        link_base=".claude/knowledge",
        scope_caps=frozenset(),
    )
    assert index == (
        "- [Alpha](.claude/knowledge/AGENT_ALPHA.md)\n"
        "- [Beta](.claude/knowledge/AGENT_BETA.md)\n"
        "- [Zulu](.claude/knowledge/AGENT_ZULU.md)\n"
        "- [Mike](.claude/knowledge/AGENT_MIKE.md)"
    )


# --- Slots : un artefact déclare ce qu'il COMPOSE, 0..N agents déclarent ce qu'ils REMPLISSENT ----


def test_the_root_template_carries_the_knowledge_index():
    """Le `CLAUDE.md` de la racine DOIT porter `{{knowledge_index}}`.

    Défaut trouvé le 2026-08-06, et resté invisible sept semaines : le template de base ne portait
    pas le slot, et le seul template qui l'avait (`CLAUDE.md.tpl`) n'était rendu que dans la couche
    domaine — elle-même injoignable (ADR-0060). L'index de routage statique, qui remplace le serveur
    MCP abandonné par ADR-0006, n'avait donc **jamais** atteint le contexte d'une session.

    Rien ne casse quand un index n'est pas chargé : l'agent travaille simplement sans savoir que 29
    bases de connaissance existent. Le silence est le mode de défaillance, d'où ce test.

    La raison d'origine de l'omission (« racine neutre, pas de savoir Snowflake pour un repo JS ») a
    disparu au lot 2 : l'index est filtré par capacité.
    """
    tpl = (setup.CORE_DIR / "CLAUDE-base.md.tpl").read_text(encoding="utf-8")
    assert "{{knowledge_index}}" in tpl


def test_slot_marker_is_rendered_into_the_index(tmp_path, monkeypatch):
    """Oracle : le marqueur `[slot]` est rendu, et seulement pour les agents qui en déclarent un.

    C'est lui qui permet à une commande de trouver ses contributeurs sans ouvrir N fichiers — le
    coût que la version « lookup par convention de nommage » faisait payer à chaque invocation.
    """
    pub = tmp_path / "pub" / "knowledge"
    pub.mkdir(parents=True)
    (pub / "AGENT_PLAIN.md").write_text("# Plain\n", encoding="utf-8")
    (pub / "AGENT_CONTRIB.md").write_text(
        "---\nslot: review\n---\n# Contrib\n", encoding="utf-8"
    )
    monkeypatch.setattr(setup.profile, "corpus_roots", lambda: [tmp_path / "pub"])

    index = setup.build_knowledge_index(
        {},
        tmp_path / "profile.yaml",
        link_base=".claude/knowledge",
        scope_caps=frozenset(),
    )
    assert index == (
        "- [Contrib](.claude/knowledge/AGENT_CONTRIB.md) `[review]`\n"
        "- [Plain](.claude/knowledge/AGENT_PLAIN.md)"
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
