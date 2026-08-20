"""corpus_roots() — a BASE carried by the code, unconditional (ADR-0069).

`corpus-public` does not declare itself: its position relative to the moteur is fixed by the repo,
so it is a constant (`DEFAULT_CORPUS_ROOTS`), never a configuration line. It used to be carried by a
committed `corpus-roots.txt`, removed since.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common  # noqa: E402


def _point(monkeypatch, install: Path):
    """Redirige la base (SCRIPT_DIR) vers un répertoire de test isolé."""
    monkeypatch.setattr(common, "SCRIPT_DIR", install)
    monkeypatch.setattr(common, "DEFAULT_CORPUS_ROOTS", [install / "corpus-public"])
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


def test_corpus_roots_is_just_the_base(tmp_path, monkeypatch):
    # Rien de déclarable : un clone frais trouve son corpus public, un uv tool install aussi.
    (tmp_path / "corpus-public").mkdir()
    _point(monkeypatch, install=tmp_path)

    assert common.corpus_roots() == [(tmp_path / "corpus-public").resolve()]


def test_env_replaces_everything_including_the_base(tmp_path, monkeypatch):
    # Sémantique inchangée : un override explicite veut dire « exactement ça ». La base n'y échappe
    # pas — c'est le seul moyen de déplacer `corpus-public`, puisqu'il n'est plus déclaratif.
    (tmp_path / "corpus-public").mkdir()
    only = tmp_path / "only"
    only.mkdir()
    _point(monkeypatch, install=tmp_path)
    monkeypatch.setenv(common.CORPUS_ROOT_ENV, str(only))

    assert common.corpus_roots() == [only.resolve()]


def test_the_removed_pointer_file_is_never_read_again(tmp_path, monkeypatch):
    # Coupure nette : un `corpus-roots.txt` résiduel dans un clone est du bruit, jamais une source.
    # Sans ce test, réintroduire la lecture passerait tous les autres cas.
    (tmp_path / "corpus-public").mkdir()
    stale = tmp_path / "corpus-roots.txt"
    stale.write_text("../ancien-corpus\n", encoding="utf-8")
    _point(monkeypatch, install=tmp_path)

    assert common.corpus_roots() == [(tmp_path / "corpus-public").resolve()]
    assert not hasattr(common, "CORPUS_POINTER_FILE")


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
