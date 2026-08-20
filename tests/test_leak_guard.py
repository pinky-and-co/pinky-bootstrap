"""Leak guard de-leak (chantier 0001, card leak-guard-deleak) — the mechanism carries no literal.

Proves the three former hardcodes are now data-driven, against a SYNTHETIC corpus (never the real
one, so the test does not drift with core/):
  - leak patterns = UNION of every `visibility: private` profile's leak_patterns / leak_patterns_file;
  - a `visibility: private` profile is refused as a --check-public target (fail-safe);
  - no configured target, or no private profile, degrades to a clean no-op — never a crash;
  - instance identity (org / asset host from docs_identity.json) is hunted too — the `pinky`-shaped
    strings the codename hunt lets through.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


def _write_profile(root: Path, name: str, body: str) -> None:
    """Drop a minimal <root>/profiles/<name>/profile.yaml for iter_profiles/load_profile to find."""
    d = root / "profiles" / name
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(f"name: {name}\n{body}", encoding="utf-8")


def test_patterns_are_union_of_private_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, str(tmp_path))
    _write_profile(
        tmp_path,
        "priv",
        "visibility: private\n"
        "leak_patterns: [Alpha, beta]\n"
        "leak_patterns_file: extra.txt\n",  # relative → resolved against the profile dir
    )
    # the out-of-git file lives next to the profile.yaml (relative resolution target)
    (tmp_path / "profiles" / "priv" / "extra.txt").write_text(
        "# out-of-git\nFileCode\n\n", encoding="utf-8"
    )
    _write_profile(
        tmp_path, "pub", "visibility: public\nleak_patterns: [shouldnotcount]\n"
    )

    # lowercased, de-duplicated, sorted; the public profile's list is ignored.
    assert setup.public_leak_patterns() == ("alpha", "beta", "filecode")


def test_no_private_profile_means_no_patterns(tmp_path, monkeypatch):
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, str(tmp_path))
    _write_profile(tmp_path, "pub", "visibility: public\n")
    assert setup.public_leak_patterns() == ()


def test_load_patterns_file_relative_comments_and_absent(tmp_path):
    f = tmp_path / "pats.txt"
    f.write_text("# comment\nPluto\n\n  Pythia  \n", encoding="utf-8")
    assert setup._load_patterns_file("pats.txt", tmp_path) == ["pluto", "pythia"]
    # absent file → no patterns, never a crash
    assert setup._load_patterns_file("nope.txt", tmp_path) == []


def test_check_public_refuses_private_target(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, str(tmp_path))
    _write_profile(tmp_path, "priv", "visibility: private\n")
    with pytest.raises(SystemExit) as exc:
        setup.check_public("priv")
    assert exc.value.code == 2
    assert "refuses private profile" in capsys.readouterr().out


def test_check_public_no_target_is_clean_noop(capsys):
    # No --profile → nothing to scan, return 0 (not a failure).
    assert setup.check_public(None) == 0
    assert "no public profile to scan" in capsys.readouterr().out.lower()


def test_identity_patterns_from_private_docs_identity(tmp_path, monkeypatch):
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, str(tmp_path))
    _write_profile(tmp_path, "priv", "visibility: private\n")
    (tmp_path / "profiles" / "priv" / "docs_identity.json").write_text(
        json.dumps(
            {
                "github_org": "AcmeCorp",
                "header_image_url": "https://assets.acme-suite.io/logo.png",
            }
        ),
        encoding="utf-8",
    )
    # a PUBLIC profile's identity is never a source (only visibility:private is)
    _write_profile(tmp_path, "pub", "visibility: public\n")
    (tmp_path / "profiles" / "pub" / "docs_identity.json").write_text(
        json.dumps({"github_org": "ShouldNotCount"}), encoding="utf-8"
    )
    # org + asset host, lowercased and sorted; the public profile's org is ignored
    assert setup.public_identity_patterns() == ("acmecorp", "assets.acme-suite.io")


def test_identity_patterns_empty_without_docs_identity(tmp_path, monkeypatch):
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, str(tmp_path))
    # private profile but no sibling docs_identity.json → no identity to protect, no crash
    _write_profile(tmp_path, "priv", "visibility: private\nleak_patterns: [x]\n")
    assert setup.public_identity_patterns() == ()


# --- Le rendu de contrôle est borné à la racine qui porte le profil scanné -----------------------

_PUBLIC_PROFILE_BODY = (
    "visibility: public\n"
    "knowledge_agents: []\n"
    "knowledge_roots: [knowledge/]\n"
    "model_routing: {fast: f, default: d, thorough: t}\n"
)


def _seed_public_root(root: Path) -> None:
    """Racine de corpus publique minimale mais RÉELLE : l'agent que les .tpl exigent.

    `{{agent:AGENT_BRANCH.md}}` est un token obligatoire — non résolu, le rendu sort en erreur.
    Le poser ici garde le test sur un corpus synthétique (il ne dérive donc pas avec le vrai) tout
    en exerçant le vrai chemin de rendu. `AGENT_GITMOJI.md` n'en fait plus partie depuis sa
    relocalisation 2026-08-09 dans `core/skills/commit/` — les .tpl ne le référencent plus.
    """
    kdir = root / "knowledge"
    kdir.mkdir(parents=True)
    for name in ("AGENT_BRANCH.md",):
        (kdir / name).write_text(
            f"# {name}\n\n> Agent public de test.\n", encoding="utf-8"
        )


def test_check_public_ignores_the_other_roots_private_corpora(
    tmp_path, monkeypatch, capsys
):
    """`--check-public` rend la vitrine du moteur, pas celle de la machine qui le lance.

    Le garde-fou fabrique en mémoire le CLAUDE.md que verrait un clone nu, puis y chasse les
    codenames. Tant qu'il résout ses agents par `corpus_roots()` — qui rend TOUTES les racines
    montées — son verdict dépend de la machine : vert chez l'autrice, potentiellement rouge chez
    quelqu'un qui monte un corpus privé de plus. Un contrôle dont le résultat dépend du poste ne
    prouve rien, d'où le bornage à la racine qui porte le profil scanné.

    Le corpus privé de ce test porte un agent SANS `capability:` (socle) : c'est le cas qui traverse
    tous les filtres, donc le seul qui prouve le bornage lui-même.
    """
    pub_root, priv_root = tmp_path / "pub", tmp_path / "priv"
    _seed_public_root(pub_root)
    _write_profile(pub_root, "vitrine", _PUBLIC_PROFILE_BODY)
    _write_profile(
        priv_root, "instance", "visibility: private\nleak_patterns: [secretcode]\n"
    )
    priv_knowledge = priv_root / "profiles" / "instance" / "knowledge"
    priv_knowledge.mkdir(parents=True)
    (priv_knowledge / "AGENT_SECRETCODE_INFRA.md").write_text(
        "# AGENT_SECRETCODE_INFRA.md — infra SecretCode\n", encoding="utf-8"
    )
    monkeypatch.setenv(setup.CORPUS_ROOT_ENV, f"{pub_root}{os.pathsep}{priv_root}")

    assert setup.check_public("vitrine") == 0
    assert "secretcode" not in capsys.readouterr().out.lower()


def test_owning_corpus_root_is_derived_not_configured(tmp_path):
    """Oracle sur la dérivation : `<racine>/profiles/<nom>/profile.yaml` → `<racine>`.

    Aucun littéral d'instance ne rentre dans le garde-fou (c'est sa raison d'être, cf. son
    docstring) : la borne se lit dans le chemin du profil lui-même. Un profil passé par chemin
    arbitraire, hors de cette forme, rend None — l'appelant dégrade alors explicitement au lieu de
    remonter deux niveaux au hasard.
    """
    assert (
        setup.owning_corpus_root(
            tmp_path / "corpus" / "profiles" / "x" / "profile.yaml"
        )
        == tmp_path / "corpus"
    )
    assert setup.owning_corpus_root(tmp_path / "ailleurs" / "profile.yaml") is None


def test_public_scan_covers_all_shipped_core_subdirs():
    # Angle mort relevé par l'audit : status-lines / pre-commit / conventions shippent
    # dans le moteur public et doivent être leak-scannés comme rules/commands/agents.
    assert {
        "rules",
        "commands",
        "agents",
        "skills",
        "status-lines",
        "hooks",
        "pre-commit",
        "conventions",
    } <= set(setup.PUBLIC_SCAN_SUBDIRS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
