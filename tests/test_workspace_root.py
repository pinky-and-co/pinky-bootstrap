"""find_workspace_root() — le moteur ne dérive plus rien de son chemin d'installation (ADR-0065).

`WORKSPACE_ROOT` valait `SCRIPT_DIR.parent`, c'est-à-dire « ce qui se trouve au-dessus de là où ce
code a été dépaqueté ». Ça n'a jamais marché que parce que le moteur est cloné DANS le workspace
qu'il sert. Installé ailleurs, la même expression désigne le préfixe d'installation, et
`discover_repos()` — qui globe `WORKSPACE_ROOT` — scanne alors `site-packages` et trouve zéro repo.
Aucune erreur, juste une distribution devenue no-op silencieux.

C'est ce silence que ces tests attaquent : chaque cas met le marqueur et le code dans des arbres
DISJOINTS, pour qu'une résolution qui retomberait sur le chemin d'install ne puisse pas passer
inaperçue. Sur la machine de l'autrice les deux coïncident — un test qui les laisserait coïncider ne
prouverait rien du tout.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common  # noqa: E402


def _no_env(monkeypatch):
    monkeypatch.delenv(common.WORKSPACE_ROOT_ENV, raising=False)


def _mark(path: Path) -> None:
    """Create a REAL marker at `path` — `.pinky/config.txt`, matching what `init_workspace()`
    actually writes. Not just the bare directory: see `test_an_unrelated_pinky_dir_is_not_a_marker`
    for why the distinction is load-bearing, not pedantry."""
    marker = path / common.MARKER_DIR_NAME
    marker.mkdir(parents=True, exist_ok=True)
    (marker / "config.txt").write_text("", encoding="utf-8")


def test_marker_in_the_start_dir_itself(tmp_path, monkeypatch):
    _no_env(monkeypatch)
    _mark(tmp_path)

    assert common.find_workspace_root(tmp_path) == tmp_path.resolve()


def test_marker_found_by_walking_up(tmp_path, monkeypatch):
    # Le cas réel : la session tourne dans un repo, le marqueur est deux crans au-dessus.
    _no_env(monkeypatch)
    _mark(tmp_path)
    deep = tmp_path / "pinky-core" / "src"
    deep.mkdir(parents=True)

    assert common.find_workspace_root(deep) == tmp_path.resolve()


def test_nearest_marker_wins(tmp_path, monkeypatch):
    # Un workspace imbriqué dans un autre : c'est le plus proche qui gagne, jamais le plus haut.
    _no_env(monkeypatch)
    outer = tmp_path
    inner = tmp_path / "inner"
    inner.mkdir()
    _mark(outer)
    _mark(inner)

    assert common.find_workspace_root(inner) == inner.resolve()


def test_env_wins_over_a_marker(tmp_path, monkeypatch):
    # L'override explicite doit gagner même quand un marqueur est juste là — sinon il n'en est pas
    # un, et il n'y a plus d'échappatoire pour un cas non prévu (CI, script hors workspace).
    _mark(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(common.WORKSPACE_ROOT_ENV, str(elsewhere))

    assert common.find_workspace_root(tmp_path) == elsewhere.resolve()


def test_an_unrelated_pinky_dir_is_not_a_marker(tmp_path, monkeypatch):
    # Le bug réel, trouvé en redistribuant à `pinky-provider` (2026-08-07) : ce repo porte depuis
    # son tout premier commit un `.pinky/schemas/` qui n'a RIEN à voir avec le marqueur workspace
    # (config IaC interne, référencée par son propre CLI). Un check sur la seule présence du
    # dossier `.pinky/` traitait `pinky-provider` lui-même comme la racine du workspace dès qu'une
    # session tournait avec ce repo pour `cwd` — `discover_repos()` y trouvait alors zéro repo, le
    # même échec silencieux qu'ADR-0065 existe pour tuer, réintroduit par un check trop large.
    # `config.txt` — écrit sans condition par `init_workspace()` — est ce qui distingue un vrai
    # marqueur d'un dossier homonyme sans rapport.
    repo = tmp_path / "pinky-provider"
    (repo / common.MARKER_DIR_NAME / "schemas").mkdir(parents=True)
    (repo / common.MARKER_DIR_NAME / "schemas" / "warehouse.schema.json").write_text(
        "{}", encoding="utf-8"
    )
    _mark(tmp_path)  # le VRAI marqueur, un cran au-dessus
    monkeypatch.delenv(common.WORKSPACE_ROOT_ENV, raising=False)

    assert common.find_workspace_root(repo) == tmp_path.resolve()


def test_no_marker_anywhere_falls_back_to_the_install_layout(tmp_path, monkeypatch):
    # Rétro-compatibilité : un moteur cloné dans son workspace, rien de configuré, se comporte
    # exactement comme avant l'ADR-0065. C'est ce qui rend la migration non bloquante.
    _no_env(monkeypatch)
    fake_install = tmp_path / "workspace" / "pinky-workspace"
    fake_install.mkdir(parents=True)
    monkeypatch.setattr(common, "SCRIPT_DIR", fake_install)
    isolated = tmp_path / "somewhere-else"
    isolated.mkdir()

    assert common.find_workspace_root(isolated) == (tmp_path / "workspace")


def test_a_file_named_pinky_is_not_a_marker(tmp_path, monkeypatch):
    # `.is_dir()`, pas `.exists()` : un fichier homonyme ne doit pas capturer la résolution, sinon
    # un `.pinky` déposé par erreur détourne silencieusement tout le workspace.
    _no_env(monkeypatch)
    (tmp_path / common.MARKER_DIR_NAME).write_text("pas un marqueur", encoding="utf-8")
    real = tmp_path / "nested"
    real.mkdir()
    monkeypatch.setattr(common, "SCRIPT_DIR", tmp_path / "install" / "moteur")

    assert common.find_workspace_root(real) == (tmp_path / "install")


def test_init_workspace_creates_a_findable_marker(tmp_path, monkeypatch):
    # Boucle fermée : ce que --init-workspace écrit doit être ce que le résolveur trouve. Les deux
    # moitiés testées séparément laisseraient passer un désaccord sur le nom du répertoire.
    _no_env(monkeypatch)
    assert common.init_workspace(tmp_path) is True

    assert (tmp_path / common.MARKER_DIR_NAME / "config.txt").is_file()
    assert common.find_workspace_root(tmp_path) == tmp_path.resolve()


def test_init_workspace_never_overwrites_an_existing_config(tmp_path):
    # Idempotence : `pinky install` l'appellera à chaque mise à jour. Écraser la config d'une
    # machine configurée à cette occasion serait une perte de données silencieuse.
    marker = tmp_path / common.MARKER_DIR_NAME
    marker.mkdir()
    config = marker / "config.txt"
    config.write_text("default_profile = mine\n", encoding="utf-8")

    assert common.init_workspace(tmp_path) is True
    assert config.read_text(encoding="utf-8") == "default_profile = mine\n"


def test_init_workspace_writes_no_instance_value(tmp_path):
    # Le squelette ne porte AUCUNE valeur : le moteur ne transporte pas de littéral d'instance, et
    # une valeur d'exemple qui marche par hasard se garde par accident. Toutes les clés commentées.
    common.init_workspace(tmp_path)
    written = (tmp_path / common.MARKER_DIR_NAME / "config.txt").read_text(
        encoding="utf-8"
    )

    assert common._read_config(tmp_path / common.MARKER_DIR_NAME / "config.txt") == {}
    for key in (
        "default_profile",
        "default_public_profile",
        "repo_globs",
        "internal_dep_prefix",
        "agent_identity",
        "machine_capabilities",
        "corpus_roots_local",
    ):
        assert f"# {key} =" in written, f"clé absente du squelette : {key}"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
