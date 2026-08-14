"""apply_instance_overrides() — les réglages d'outil de CETTE machine, par-dessus le profil (ADR-0069).

Un `profile.yaml` versionné mélangeait deux natures. Ce qui produit un **artefact partagé** (code,
doc, commit — lu par quelqu'un d'autre un jour) y reste ; ce qui règle l'outil pour cette session,
sur cette machine, appartient à l'instance.

Ce n'est pas du rangement : `pluto` est partagé avec un second développeur, donc passer `chat: fr` à
`de` pour soi change aussi ce que l'AUTRE reçoit, ou coûte un commit/revert par essai.

Deux invariants portent la sûreté du mécanisme, et ont chacun leur test ci-dessous :
la surcharge passe par `validate_profile` (jamais un second chemin de validation), et une clé hors
allowlist échoue au lieu d'être ignorée (une surcharge silencieusement inerte est le défaut exact
que la validation stricte des profils existe pour refuser).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common, profile as prof  # noqa: E402

BASE = {
    "name": "essai",
    "knowledge_agents": [],
    "knowledge_roots": [],
    "model_routing": {
        "provider": "anthropic",
        "fast": "f",
        "default": "d",
        "thorough": "t",
    },
    "languages": {"default": "en", "overrides": {"chat": "fr", "comments": "fr"}},
    "behavior": {"challenge": "on", "vocabulary": "teach"},
}


def test_no_instance_key_returns_an_equal_profile():
    # Rétro-compatibilité : une machine qui ne surcharge rien rend exactement comme avant.
    assert prof.apply_instance_overrides(BASE, {}) == BASE


def test_flat_instance_keys_are_not_profile_paths():
    # `default_profile`, `repo_globs`… cohabitent dans le même fichier et ne sont pas des chemins de
    # profil. Sans cette distinction, chaque clé d'instance existante ferait échouer le build.
    config = {
        "default_profile": "pinky",
        "repo_globs": "pinky-*",
        "agent_identity": "x",
    }
    assert prof.apply_instance_overrides(BASE, config) == BASE


def test_an_allowed_knob_wins_over_the_profile():
    merged = prof.apply_instance_overrides(BASE, {"behavior.vocabulary": "assume"})

    assert merged["behavior"]["vocabulary"] == "assume"


def test_a_knob_absent_from_the_config_is_never_touched():
    merged = prof.apply_instance_overrides(BASE, {"behavior.vocabulary": "assume"})

    assert merged["behavior"]["challenge"] == "on"
    assert merged["languages"]["overrides"] == {"chat": "fr", "comments": "fr"}
    assert merged["model_routing"]["thorough"] == "t"


def test_the_loaded_profile_is_not_mutated():
    # Le profil chargé sert aussi à des contrôles qui ne doivent PAS voir la machine
    # (`--check-public`, `--into`). Une mutation en place les contaminerait par effet de bord.
    prof.apply_instance_overrides(BASE, {"behavior.challenge": "off"})

    assert BASE["behavior"]["challenge"] == "on"


def test_an_override_creates_the_branch_when_the_profile_omits_it():
    """Le trou `pluto` : le profil n'a AUCUN bloc `behavior:`, donc `teaching_mode` y arrivait à
    `off` par défaut gracieux alors que personne n'avait décidé cette valeur. La surcharge doit
    pouvoir trancher sans exiger qu'on édite d'abord le profil partagé.
    """
    bare = {k: v for k, v in BASE.items() if k != "behavior"}

    merged = prof.apply_instance_overrides(bare, {"behavior.vocabulary": "explain"})

    assert merged["behavior"] == {"vocabulary": "explain"}


def test_precedence_is_instance_over_profile_over_engine_default():
    # Les trois niveaux d'un coup, sur le rendu réel : `challenge` vient du profil, `vocabulary`
    # de l'instance, `derail_handling` du défaut moteur (déclaré nulle part).
    merged = prof.apply_instance_overrides(
        {**BASE, "behavior": {"challenge": "off"}}, {"behavior.vocabulary": "explain"}
    )
    rendered = prof.render_behavior(merged)

    assert "**Challenge decisions** — off" in rendered
    assert "**Vocabulary** — explain" in rendered
    assert "park side-quests" in rendered  # défaut moteur, jamais déclaré


def test_a_dotted_key_outside_the_allowlist_fails_the_build(capsys):
    # `comments` produit un artefact committé (un commentaire de code) : c'est de la politique, pas
    # du confort de session. Refusé, jamais ignoré.
    with pytest.raises(SystemExit):
        prof.apply_instance_overrides(BASE, {"languages.overrides.comments": "de"})

    out = capsys.readouterr().out
    assert "languages.overrides.comments" in out
    assert "profile.yaml" in out


def test_only_the_chat_axis_is_overridable_among_the_nine():
    # Verrouille la coupure elle-même : les huit autres axes finissent tous dans un fichier.
    overridable = {
        k.rsplit(".", 1)[1]
        for k in prof.INSTANCE_OVERRIDABLE
        if k.startswith("languages.overrides.")
    }

    assert overridable == {"chat"}


def test_the_allowlist_tracks_the_behavior_knobs():
    # Dérivée du vocabulaire existant, pas recopiée : ajouter un knob le rend surchargeable sans
    # qu'on ait à penser à cette liste.
    assert {f"behavior.{k}" for k in prof.BEHAVIOR_KNOBS} <= prof.INSTANCE_OVERRIDABLE


def test_an_invalid_value_is_caught_by_validate_profile_not_a_second_path(
    tmp_path, capsys
):
    """L'invariant qui compte : une valeur d'instance franchit le MÊME contrôle que la même valeur
    écrite dans un profile.yaml. Un second chemin de validation divergerait du premier.
    """
    merged = prof.apply_instance_overrides(BASE, {"behavior.challenge": "peut-etre"})

    with pytest.raises(SystemExit):
        prof.validate_profile(merged, tmp_path / "profile.yaml")

    assert "behavior.challenge='peut-etre'" in capsys.readouterr().out


def test_the_chat_override_reaches_the_rendered_language_policy():
    # Oracle de bout en bout : la surcharge doit atteindre le texte que la session lit réellement,
    # pas seulement le dict.
    merged = prof.apply_instance_overrides(BASE, {"languages.overrides.chat": "de"})

    assert "**Chat output to you is `de`.**" in prof.render_languages(merged)


def test_the_real_profiles_render_identically_without_any_override():
    """Rétro-compat sur les profils RÉELS, pas sur une fixture : une machine qui n'a rien surchargé
    doit obtenir le même rendu qu'avant le mécanisme.

    Un checkout CI n'a que le corpus public, donc seul `example` est garanti présent — les autres
    sont testés quand ils sont là (`tests/conftest.py`).
    """
    available = [
        cr / "profiles" / name / "profile.yaml"
        for cr in common.corpus_roots()
        for name in ("example", "pinky", "pluto")
        if (cr / "profiles" / name / "profile.yaml").is_file()
    ]
    assert available, (
        "aucun profil résolvable — le corpus public devrait toujours l'être"
    )

    for path in available:
        loaded, _ = common.load_profile(str(path))
        merged = prof.apply_instance_overrides(loaded, {})
        assert prof.render_behavior(merged) == prof.render_behavior(loaded)
        assert prof.render_languages(merged) == prof.render_languages(loaded)


def test_into_repo_render_ignores_this_machines_overrides(tmp_path, monkeypatch):
    """La propriété de SÛRETÉ du placement, pas seulement de la fusion.

    `--into` produit un `CLAUDE.md` que l'auteure committe et que quelqu'un d'autre clone. Y
    appliquer ses réglages de machine y expédierait ses préférences perso déguisées en politique du
    repo. Le sujet réel est exercé (un `install_into_repo` complet), pas un grep de source : c'est
    la seule façon qu'une régression du site d'appel soit vue.
    """
    monkeypatch.setattr(
        common, "_WORKSPACE_DEFAULTS", {"languages.overrides.chat": "de"}
    )
    monkeypatch.setattr(prof, "_WORKSPACE_DEFAULTS", {"languages.overrides.chat": "de"})

    prof.install_into_repo("example", tmp_path)

    rendered = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "**Chat output to you is `en`.**" in rendered
    assert "`de`" not in rendered


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_multi_agent_is_overridable_per_machine():
    """Capacité de la machine et quota du compte : aucun artefact partagé, donc côté instance.

    La valeur arrive en TEXTE (`key = value`) et doit franchir le même contrôle que l'entier qu'un
    profile.yaml produit — un second chemin de validation divergerait du premier.
    """
    merged = prof.apply_instance_overrides(
        BASE, {"multi_agent.max_parallel_tasks": "2"}
    )

    assert "**Max concurrent Tasks:** 2" in prof.render_multi_agent(merged)


def test_a_bogus_instance_override_is_caught_by_validate_profile(tmp_path, capsys):
    merged = prof.apply_instance_overrides(
        BASE, {"multi_agent.max_parallel_tasks": "zéro"}
    )

    with pytest.raises(SystemExit):
        prof.validate_profile(merged, tmp_path / "profile.yaml")

    assert "multi_agent.max_parallel_tasks" in capsys.readouterr().out
