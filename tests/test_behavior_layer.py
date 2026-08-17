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


# ── multi_agent — le 3e knob (rendu supprimé 2026-08-17, la validation reste) ────────────────


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
