"""find_workspace_root() — le moteur ne dérive plus rien de son chemin d'installation (ADR-0065).

`WORKSPACE_ROOT` valait `SCRIPT_DIR.parent`, c'est-à-dire « ce qui se trouve au-dessus de là où ce
code a été dépaqueté ». Ça n'a jamais marché que parce que le moteur est cloné DANS le workspace
qu'il sert. Installé ailleurs, la même expression désigne le préfixe d'installation, et
`discover_repos()` — qui scanne `WORKSPACE_ROOT` — trouve alors zéro repo dans `site-packages`.
Aucune erreur, juste une distribution devenue no-op silencieux.

C'est ce silence que ces tests attaquent : chaque cas met le marqueur et le code dans des arbres
DISJOINTS, pour qu'une résolution qui retomberait sur le chemin d'install ne puisse pas passer
inaperçue. Sur la machine de l'autrice les deux coïncident — un test qui les laisserait coïncider ne
prouverait rien du tout.

Le marqueur lui-même est le `*.code-workspace` VSCode multi-racine — plus de fichier bespoke à créer
ou maintenir : la déclaration existe déjà pour de vraies raisons dès qu'un opérateur monte plusieurs
racines.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import common


def _no_env(monkeypatch):
    monkeypatch.delenv(common.WORKSPACE_ROOT_ENV, raising=False)


def _mark(path: Path, name: str = "pinky.code-workspace") -> None:
    """Create a REAL `*.code-workspace` marker file at `path`."""
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text("{}", encoding="utf-8")


def test_marker_in_the_start_dir_itself(tmp_path, monkeypatch):
    _no_env(monkeypatch)
    _mark(tmp_path)

    assert common.find_workspace_root(tmp_path) == tmp_path.resolve()


def test_marker_found_by_walking_up(tmp_path, monkeypatch):

    _no_env(monkeypatch)
    _mark(tmp_path)
    deep = tmp_path / "pinky-core" / "src"
    deep.mkdir(parents=True)

    assert common.find_workspace_root(deep) == tmp_path.resolve()


def test_nearest_marker_wins(tmp_path, monkeypatch):

    _no_env(monkeypatch)
    outer = tmp_path
    inner = tmp_path / "inner"
    inner.mkdir()
    _mark(outer)
    _mark(inner)

    assert common.find_workspace_root(inner) == inner.resolve()


def test_env_wins_over_a_marker(tmp_path, monkeypatch):

    _mark(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv(common.WORKSPACE_ROOT_ENV, str(elsewhere))

    assert common.find_workspace_root(tmp_path) == elsewhere.resolve()


def test_a_directory_named_code_workspace_is_not_a_marker(tmp_path, monkeypatch):

    _no_env(monkeypatch)
    (tmp_path / "pinky.code-workspace").mkdir()
    real = tmp_path / "nested"
    real.mkdir()
    monkeypatch.setattr(common, "SCRIPT_DIR", tmp_path / "install" / "moteur")

    assert common.find_workspace_root(real) == (tmp_path / "install")


def test_no_marker_anywhere_falls_back_to_the_install_layout(tmp_path, monkeypatch):

    _no_env(monkeypatch)
    fake_install = tmp_path / "workspace" / "pinky-workspace"
    fake_install.mkdir(parents=True)
    monkeypatch.setattr(common, "SCRIPT_DIR", fake_install)
    isolated = tmp_path / "somewhere-else"
    isolated.mkdir()

    assert common.find_workspace_root(isolated) == (tmp_path / "workspace")


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
