"""corpus_roots() — une BASE portée par le code + la clé d'instance qui s'y ajoute (ADR-0069).

`corpus-public` ne se déclare plus : sa position relative au moteur est fixée par le dépôt, donc
c'est une constante (`DEFAULT_CORPUS_ROOTS`), pas une ligne de configuration. Elle était portée par
un `corpus-roots.txt` committé, supprimé depuis.

Ce que ces tests verrouillent, et pourquoi ils sont écrits ainsi : la base est **toujours préfixée**,
jamais un repli. Le code d'avant faisait `if roots: return roots` avant d'y toucher — y déplacer
`corpus-public` sans changer ça l'aurait fait disparaître sur toute machine déclarant une racine
d'instance. Personne ne l'aurait vu : le moteur aurait continué de résoudre les profils privés, en
rendant un index de connaissance et un `--check-public` faux, sans une seule erreur.

Seule la clé `corpus_roots_local` de `<racine>/.pinky/config.txt` (gitignorée) reste déclarative :
un drive synchronisé a un point de montage différent sur chaque machine, ce qu'aucune constante ne
peut exprimer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common  # noqa: E402


def _point(
    monkeypatch, *, local: str | None, install: Path, workspace: Path | None = None
):
    """Redirige la base (SCRIPT_DIR), la racine du workspace et la clé d'instance.

    Args:
        monkeypatch: fixture pytest.
        local: valeur brute de `corpus_roots_local`, ou None pour une config vide.
        install: tient lieu de SCRIPT_DIR — le chemin d'INSTALL du moteur.
        workspace: tient lieu de WORKSPACE_ROOT — la base des entrées relatives d'instance.
            Défaut `install`, pour les cas où la distinction n'est pas le sujet.
    """
    monkeypatch.setattr(common, "SCRIPT_DIR", install)
    monkeypatch.setattr(common, "WORKSPACE_ROOT", workspace or install)
    monkeypatch.setattr(common, "DEFAULT_CORPUS_ROOTS", [install / "corpus-public"])
    monkeypatch.setattr(
        common,
        "_WORKSPACE_DEFAULTS",
        {"corpus_roots_local": local} if local else {},
    )
    monkeypatch.delenv(common.CORPUS_ROOT_ENV, raising=False)


def test_default_base_is_corpus_public_and_only_that():
    """Oracle sur la constante elle-même : le moteur ne se déclare pas racine de corpus.

    `SCRIPT_DIR` figurait dans l'ancien repli, fossile d'avant ADR-0012 quand `knowledge/` et
    `profiles/` vivaient à la racine du moteur. Ils sont sous `corpus-public/` depuis, donc le
    garder n'aurait résolu aucun fichier — juste ajouté une racine morte au « Corpus roots
    searched » d'un message d'erreur.
    """
    assert common.DEFAULT_CORPUS_ROOTS == [common.SCRIPT_DIR / "corpus-public"]
    assert not (common.SCRIPT_DIR / "profiles").exists()
    assert not (common.SCRIPT_DIR / "knowledge").exists()


def test_corpus_public_survives_a_declared_local_root(tmp_path, monkeypatch):
    """LE test — la régression que le repli aurait produite.

    Une machine qui déclare une racine d'instance (le cas normal : c'est ce que `.pinky/config.txt`
    existe pour faire) doit garder `corpus-public`. Avec un repli, cette machine-là exactement le
    perdait.
    """
    (tmp_path / "corpus-public").mkdir()
    drive = tmp_path / "drive" / "shared"
    drive.mkdir(parents=True)
    _point(monkeypatch, local=str(drive), install=tmp_path)

    assert common.corpus_roots() == [
        (tmp_path / "corpus-public").resolve(),
        drive.resolve(),
    ]


def test_no_instance_key_gives_just_the_base(tmp_path, monkeypatch):
    # Un clone frais, rien de configuré : le moteur trouve quand même son corpus public. C'est la
    # contrainte de packaging — un `uv tool install` n'a pas de `.pinky/config.txt`.
    (tmp_path / "corpus-public").mkdir()
    _point(monkeypatch, local=None, install=tmp_path)

    assert common.corpus_roots() == [(tmp_path / "corpus-public").resolve()]


def test_instance_key_accepts_several_roots_comma_separated(tmp_path, monkeypatch):
    (tmp_path / "corpus-public").mkdir()
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _point(monkeypatch, local=f"{first} , {second}", install=tmp_path)

    assert common.corpus_roots() == [
        (tmp_path / "corpus-public").resolve(),
        first.resolve(),
        second.resolve(),
    ]


def test_relative_instance_entry_resolves_against_the_workspace_root(
    tmp_path, monkeypatch
):
    """La base est la racine du workspace — ni le chemin d'install, ni le dossier marqueur.

    Trois arbres disjoints, pour qu'aucune des deux confusions possibles ne passe :

    - contre `SCRIPT_DIR` (l'install), une entrée qui décrit le workspace pointe à côté dès que le
      moteur n'est pas cloné dedans — le défaut qu'ADR-0065 existe pour tuer ;
    - contre `MARKER_DIR` (`<racine>/.pinky`), ce que le code faisait, `_corpus-pinky` donnait
      `<racine>/.pinky/_corpus-pinky`. Invisible tant que la seule entrée relative était absolue,
      faux dès qu'on y range un sibling du workspace.
    """
    install = tmp_path / "install"
    workspace = tmp_path / "workspace"
    (install / "corpus-public").mkdir(parents=True)
    (workspace / "_corpus-prive").mkdir(parents=True)
    _point(monkeypatch, local="_corpus-prive", install=install, workspace=workspace)

    assert common.corpus_roots() == [
        (install / "corpus-public").resolve(),
        (workspace / "_corpus-prive").resolve(),
    ]


def test_env_replaces_everything_including_the_base(tmp_path, monkeypatch):
    # Sémantique inchangée : un override explicite veut dire « exactement ça ». La base n'y échappe
    # pas — c'est le seul moyen restant de déplacer `corpus-public`, puisqu'il n'est plus déclaratif.
    (tmp_path / "corpus-public").mkdir()
    only = tmp_path / "only"
    only.mkdir()
    _point(monkeypatch, local=str(tmp_path / "ignored"), install=tmp_path)
    monkeypatch.setenv(common.CORPUS_ROOT_ENV, str(only))

    assert common.corpus_roots() == [only.resolve()]


def test_duplicate_root_declared_twice_is_kept_once(tmp_path, monkeypatch):
    # Déclarer `corpus-public` dans la clé d'instance (par réflexe, ou par migration d'un ancien
    # corpus-roots.txt) ne doit pas le faire apparaître deux fois.
    (tmp_path / "corpus-public").mkdir()
    _point(monkeypatch, local=str(tmp_path / "corpus-public"), install=tmp_path)

    assert common.corpus_roots() == [(tmp_path / "corpus-public").resolve()]


def test_the_removed_pointer_file_is_never_read_again(tmp_path, monkeypatch):
    # Coupure nette : un `corpus-roots.txt` résiduel dans un clone est du bruit, jamais une source.
    # Sans ce test, réintroduire la lecture passerait tous les autres cas.
    (tmp_path / "corpus-public").mkdir()
    stale = tmp_path / "corpus-roots.txt"
    stale.write_text("../ancien-corpus\n", encoding="utf-8")
    _point(monkeypatch, local=None, install=tmp_path)

    assert common.corpus_roots() == [(tmp_path / "corpus-public").resolve()]
    assert not hasattr(common, "CORPUS_POINTER_FILE")


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
