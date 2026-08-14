"""Un profil doit pouvoir ne PAS déclarer d'identité de suite (card `profil-sans-identite-de-suite`).

`docs_identity.json` décrit une SUITE : un bandeau, une ligne d'appartenance, un pitch. Tous les
profils n'en sont pas une — PLUTO livre des applications, `pinky-studio` n'a jamais rendu de pitch.
`from_dict` exigeait pourtant ses sept champs, donc `_corpus-pluto` en portait **six vides** pour que
le fichier existe. Le commentaire de la card fermée qui a semé celle-ci le disait déjà : « devoir
déclarer sept champs pour dire "je n'en suis pas une" est un contournement propre, pas une réponse ».

Même renversement qu'ADR-0058 → 0062 : ce qui n'est pas déclaré **n'existe pas**, au lieu d'exister
vide. Seul `github_org` reste requis — l'URL du badge CI se construit avec, il n'a pas de forme
dégradée.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "hooks"))
from render_docs import (  # noqa: E402
    SuiteIdentity,
    render_readme_badges,
    render_readme_why,
)

MINIMAL = {"github_org": "some-org"}
FULL = {
    "github_org": "some-org",
    "header_image_url": "https://assets.example.invalid/h.png",
    "header_alt": "a suite",
    "suite_line": "Part of the [a suite](https://example.invalid) suite.",
    "pitch_heading": "Why?",
    "pitch_paragraphs": ["Un paragraphe."],
    "pitch_pills": ["rapide", "sûr"],
}


def test_a_profile_that_is_not_a_suite_needs_one_field():
    identity = SuiteIdentity.from_dict(MINIMAL)

    assert identity.github_org == "some-org"
    assert identity.header_image_url == ""
    assert identity.pitch_paragraphs == ()


def test_github_org_stays_required():
    """Le badge CI n'a pas de forme dégradée — l'absence doit échouer, pas produire une URL cassée."""
    with pytest.raises(KeyError):
        SuiteIdentity.from_dict({"header_alt": "x"})


def test_no_header_declared_means_no_broken_image(tmp_path):
    """Oracle d'égalité sur TOUT le bloc — `tests.md` § générateurs.

    Un fragment `"<img" not in` prouverait l'absence de bandeau sans rien dire du reste : c'est
    exactement l'assertion faible que le cliquet `check_weak_assertions` refuse sur un `render_*`.
    Ici le bloc entier est épinglé, donc le test voit aussi une régression de structure (marqueurs,
    `<div>`, ligne de navigation) et pas seulement le symptôme visé.
    """
    rendered = render_readme_badges(
        tmp_path / "demo-repo", SuiteIdentity.from_dict(MINIMAL)
    )

    assert rendered == (
        "<!-- pinky:readme-badges:start -->\n"
        "\n"
        '<div align="center">\n'
        "\n"
        "\n"
        "**[Install](#install) • [Documentation](#documentation) • [License](#license)**\n"
        "\n"
        "</div>\n"
        "<!-- pinky:readme-badges:end -->"
    )
    assert "<img" not in rendered  # le symptôme visé, en plus de l'oracle


def test_a_declared_header_still_renders(tmp_path):
    rendered = render_readme_badges(tmp_path, SuiteIdentity.from_dict(FULL))

    assert '<img src="https://assets.example.invalid/h.png"' in rendered


def test_no_pitch_declared_renders_empty_markers_not_a_hollow_section():
    """Oracle d'égalité : marqueurs seuls, pour que l'injection reste idempotente et qu'un pitch
    ajouté plus tard atterrisse au bon endroit — sans titre suivi de blanc entre-temps.
    """
    from render_docs import README_WHY_MARK_END, README_WHY_MARK_START

    assert render_readme_why(SuiteIdentity.from_dict(MINIMAL)) == (
        f"{README_WHY_MARK_START}\n{README_WHY_MARK_END}"
    )


def test_a_declared_pitch_still_renders_prose_and_pills():
    rendered = render_readme_why(SuiteIdentity.from_dict(FULL))

    assert "Un paragraphe." in rendered
    assert "**rapide · sûr**" in rendered


def test_pills_without_paragraphs_do_not_emit_a_stray_blank_block():
    partial = {**MINIMAL, "pitch_pills": ["seul"]}

    assert render_readme_why(SuiteIdentity.from_dict(partial)).count("\n\n") == 2


def test_the_round_trip_through_json_survives_an_absent_field():
    """`to_json` sérialise les 7 champs ; les relire ne doit pas ressusciter l'exigence."""
    import json

    again = SuiteIdentity.from_dict(
        json.loads(SuiteIdentity.from_dict(MINIMAL).to_json())
    )

    assert again == SuiteIdentity.from_dict(MINIMAL)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── nom de licence — même fichier de test : c'est le même générateur de README ─


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\n Apache License\n Version 2.0, January 2004\n", "Apache-2.0"),
        ("MIT License\n\nCopyright (c) 2026\n", "MIT"),
        ("BSD 3-Clause License\n\nCopyright\n", "BSD 3-Clause"),
        ("", "UNKNOWN"),
    ],
)
def test_license_name_survives_a_leading_blank_line(tmp_path, text, expected):
    """Le texte Apache-2.0 canonique OUVRE sur une ligne vide.

    L'ancienne version lisait la ligne 0 : elle rendait un nom vide, donc la section License du
    README aurait affiché « — see LICENSE » sur tout repo adoptant Apache. Trouvé le 2026-08-09 en
    posant la licence du moteur. La version est jointe au nom parce qu'« Apache » seul désigne trois
    licences ; « Apache-2.0 » est la forme SPDX.
    """
    from render_docs import _repo_license_name

    (tmp_path / "LICENSE").write_text(text, encoding="utf-8")

    assert _repo_license_name(tmp_path) == expected


def test_license_name_is_unknown_without_a_license_file(tmp_path):
    from render_docs import _repo_license_name

    assert _repo_license_name(tmp_path) == "UNKNOWN"
