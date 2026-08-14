"""Behavior policy — profile `behavior:` block dials interaction-style knobs (ADR-0021).

Defines "done" for the chantier-0001 card `configurable-behavior-layer`: the former manual
preamble ("challenge my decisions", "teach me the vocab", ...) becomes a profile-configurable
layer, cloning the `languages:` pattern (ADR-0011) rather than a bespoke mechanism.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


def _private_profile_available(name: str = "pinky") -> bool:
    # Un checkout CI n'a QUE le corpus public (`corpus-public`) — le sibling `_corpus-pinky`
    # n'est jamais cloné par une Action. Ce prédicat dit si le profil privé est résoluble ici,
    # pour skipper (au lieu de mentir par omission) les tests qui assertent une vraie valeur privée.
    return any(
        (cr / "profiles" / name / "profile.yaml").exists()
        for cr in setup.corpus_roots()
    )


def test_render_behavior_defaults_when_block_absent():
    rendered = setup.render_behavior({})
    assert "Challenge decisions** — push back" in rendered
    assert "Vocabulary** — assume" in rendered
    assert "Derailment handling** — park" in rendered


def test_render_behavior_oracle_all_defaults():
    """Oracle — the WHOLE slot (tests.md § generator oracle).

    Truth source: ``BEHAVIOR_KNOBS`` — every declared knob renders, in declaration order, under the
    intro paragraph and its blank line. Deriving the expected text FROM ``BEHAVIOR_KNOBS`` would be
    tautological (it would pass on a renderer that dropped a knob), so the prose is spelled out: it
    is the text an agent actually reads in CLAUDE.md. A dropped or reordered knob — invisible to
    every fragment assert below — breaks this.
    """
    assert setup.render_behavior({}) == (
        "Interaction-style knobs, set by the active profile (`behavior:`) — core rules set the "
        "baseline, the profile dials it per target. Convention only (not hook-enforced):\n"
        "\n"
        "- **Challenge decisions** — push back before executing; no rubber-stamping, "
        "zero confirmation bias.\n"
        "- **Vocabulary** — assume; the reader knows the trade's vocabulary. Use it "
        "plainly, without glossing.\n"
        "- **Derailment handling** — park side-quests (kanban `0-ideas`, see `kanban.md`) "
        "and keep the current thread going."
    )


def test_render_behavior_oracle_every_knob_dialed_off_default():
    """Oracle — the opposite corner: each knob on its non-default value, whole slot pinned."""
    assert setup.render_behavior(
        {
            "behavior": {
                "challenge": "off",
                "vocabulary": "teach",
                "derail_handling": "stop",
            }
        }
    ) == (
        "Interaction-style knobs, set by the active profile (`behavior:`) — core rules set the "
        "baseline, the profile dials it per target. Convention only (not hook-enforced):\n"
        "\n"
        "- **Challenge decisions** — off; proceed on the user's call without pushback.\n"
        "- **Vocabulary** — teach; use the real technical term AND explain it as you go, "
        "so the reader acquires it.\n"
        "- **Derailment handling** — stop and ask before following a side-quest."
    )


def test_render_behavior_dials_each_knob():
    rendered = setup.render_behavior(
        {
            "behavior": {
                "challenge": "off",
                "vocabulary": "teach",
                "derail_handling": "stop",
            }
        }
    )
    assert "Challenge decisions** — off" in rendered
    assert "Vocabulary** — teach" in rendered
    assert "Derailment handling** — stop" in rendered


def test_render_behavior_partial_override_keeps_other_defaults():
    rendered = setup.render_behavior({"behavior": {"vocabulary": "teach"}})
    assert "Vocabulary** — teach" in rendered
    assert (
        "Challenge decisions** — push back" in rendered
    )  # untouched knob stays default


def test_render_behavior_unknown_value_falls_back_to_default():
    rendered = setup.render_behavior({"behavior": {"challenge": "maybe"}})
    assert "Challenge decisions** — push back" in rendered


def test_render_behavior_handles_yaml_bare_on_off_as_booleans():
    # PyYAML parses bare `on`/`off` (unquoted) as bool True/False — the exact shape a hand-edited
    # profile.yaml produces without quoting. Must resolve like the "on"/"off" strings, not fall back.
    # Only `challenge` and `derail_handling` still take on/off values; `vocabulary` (ADR-0070) takes
    # words, which YAML never coerces — so the footgun no longer exists on that axis at all.
    rendered = setup.render_behavior({"behavior": {"challenge": False}})

    assert "Challenge decisions** — off" in rendered


def test_validate_profile_fails_on_the_renamed_teaching_mode_knob(capsys):
    """L'ancienne clé échoue et DIT ce qu'elle est devenue — jamais un drop silencieux.

    Le cas où l'auteur du profil a bel et bien configuré quelque chose : le laisser tomber le
    ferait retomber sur `assume` en le laissant croire sa configuration active. Distinct du message
    générique « unknown behavior knob », qui ne dirait pas où la valeur est partie.
    """
    profile, ppath = setup.load_profile("example")
    profile = {**profile, "behavior": {"teaching_mode": "on"}}

    with pytest.raises(SystemExit):
        setup.validate_profile(profile, ppath)

    out = capsys.readouterr().out
    assert "renamed to `vocabulary`" in out
    assert "`on` → `teach`" in out and "`off` → `assume`" in out


def test_validate_profile_fails_on_unknown_knob(capsys):
    # Strict posture (ADR-0021, aligned with the language axis + the workspace-wide "fail loud, never
    # warn-and-skip" shift): an unknown knob is a typo → hard fail, not a silent fallback.
    # Profil incident (juste une base valide à muter) → `example`, le seul profil public,
    # pour que le test tourne en CI sans le corpus privé.
    profile, ppath = setup.load_profile("example")
    profile = {
        **profile,
        "behavior": {**(profile.get("behavior") or {}), "bogus_knob": "on"},
    }
    with pytest.raises(SystemExit):
        setup.validate_profile(profile, ppath)
    assert "unknown behavior knob(s): bogus_knob" in capsys.readouterr().out


def test_validate_profile_fails_on_out_of_range_value(capsys):
    # Profil incident, idem → `example` (corpus-agnostique).
    profile, ppath = setup.load_profile("example")
    profile = {
        **profile,
        "behavior": {**(profile.get("behavior") or {}), "derail_handling": "yell"},
    }
    with pytest.raises(SystemExit):
        setup.validate_profile(profile, ppath)
    assert "behavior.derail_handling='yell'" in capsys.readouterr().out


@pytest.mark.needs_private_corpus
@pytest.mark.skipif(
    not _private_profile_available(),
    reason="profil privé `pinky` absent du checkout public (CI) — la CI annonce ce qu'elle "
    "ne couvre pas plutôt que de mentir par omission",
)
# ── multi_agent — le 3e knob, rendu depuis 2026-08-09 ────────────────────────


def test_render_multi_agent_oracle_defaults():
    """Oracle d'égalité : tout le bloc est épinglé, valeurs comprises."""
    assert setup.render_multi_agent({}) == (
        "- **Max concurrent Tasks:** 4 — the ceiling when `--parallel` dispatches one Task per "
        "target.\n"
        "- **Per-Task timeout:** 15 min — past it the orchestrator marks the Task failed and "
        "reports it, without retrying."
    )


def test_render_multi_agent_carries_the_dialed_value():
    """LE défaut corrigé : la valeur du profil devait atteindre le texte que la session lit.

    Avant, elle ne quittait jamais `profile.yaml` et `apply-convention.md` annonçait 4 en dur — un
    profil réglé sur 8 lisait donc une rule qui le contredisait.
    """
    rendered = setup.render_multi_agent({"multi_agent": {"max_parallel_tasks": 8}})

    assert "**Max concurrent Tasks:** 8" in rendered
    assert "**Per-Task timeout:** 15 min" in rendered  # knob non dialé → défaut moteur


@pytest.mark.parametrize(
    "block",
    [
        {"multi_agents": 4},  # typo sur le nom du bloc interne
        {"max_parallel_tasks": 0},  # zéro Task = pas une limite, une panne
        {"max_parallel_tasks": -2},
        {"task_timeout_minutes": "beaucoup"},
        {
            "max_parallel_tasks": True
        },  # bool EST un int en Python — jamais un compte de Tasks
    ],
)
def test_validate_profile_rejects_a_bogus_multi_agent_block(block, capsys):
    """Avant : aucun code ne lisait la clé, donc rien ne se plaignait — l'auteur du profil croyait
    sa limite active. Même posture stricte que les axes de langue et les knobs de comportement.
    """
    profile, ppath = setup.load_profile("example")

    with pytest.raises(SystemExit):
        setup.validate_profile({**profile, "multi_agent": block}, ppath)

    assert "multi_agent" in capsys.readouterr().out
