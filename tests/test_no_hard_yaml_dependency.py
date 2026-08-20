"""Le chemin de distribution doit tourner SANS pyyaml installé.

Invariant de conception, déjà énoncé dans `common.py` (« lazy: keep the dependency-free
distribution path clean ») mais que rien ne vérifiait. Il a été cassé le 2026-07-31 par un
`import yaml` en tête de `setup/profile.py` : comme `setup/__init__.py` importe `profile`,
importer le paquet suffisait à exiger pyyaml, et le job Windows — qui ne l'installe pas —
échouait à l'import, avant même d'exécuter quoi que ce soit.

Le test s'exécute dans un sous-processus où l'import de `yaml` est rendu impossible : il
mesure la propriété réelle, pas une approximation par grep.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

# Bloque `yaml` au niveau de la machinerie d'import, puis exerce le chemin de distribution.
# `--dry-run` n'écrit rien ; ce qui compte est que l'import du paquet et la découverte des repos
# aboutissent sans pyyaml.
_SCRIPT = """
import sys

class _BlockYaml:
    def find_module(self, name, path=None):
        return self if name == "yaml" or name.startswith("yaml.") else None
    def find_spec(self, name, path=None, target=None):
        if name == "yaml" or name.startswith("yaml."):
            raise ImportError("pyyaml volontairement indisponible")
        return None

sys.meta_path.insert(0, _BlockYaml())
sys.path.insert(0, {repo!r})

import setup  # doit passer sans pyyaml

# Le chemin sans profil ne doit toucher aucune fonction qui parse du YAML.
setup.discover_repos()
print("OK")
"""


def test_package_imports_and_distributes_without_pyyaml():
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(repo=str(REPO))],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        "le chemin de distribution exige pyyaml — un import doit être rendu paresseux.\n"
        f"{proc.stderr}"
    )
    assert "OK" in proc.stdout


def test_the_guard_itself_would_catch_a_top_level_import():
    """Preuve par mutation : le bloqueur d'import fonctionne vraiment.

    Sans ce contrôle, un bloqueur inopérant ferait passer le test précédent quoi qu'il arrive —
    exactement le genre de test qui ne peut pas échouer.
    """
    script = _SCRIPT.format(repo=str(REPO)).replace(
        "import setup  # doit passer sans pyyaml", "import yaml"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode != 0, "le bloqueur d'import ne bloque rien"


def test_collection_survives_without_pyyaml(tmp_path):
    """Sans pyyaml, la suite doit se COLLECTER quand même — sinon zéro test ne tourne.

    Le pendant côté tests de l'invariant ci-dessus. Un `import yaml` en tête d'un module de test ne
    fait pas tomber ce module : il fait échouer la collecte, et pytest interrompt tout
    (« Interrupted: N errors during collection »). Les 300+ tests qui n'ont rien à voir avec YAML
    ne tournent alors nulle part — c'est une panne bien plus large que la dépendance qui la cause.

    Mesuré, pas approché par grep : un faux module `yaml` qui lève à l'import est placé devant le
    vrai via PYTHONPATH, puis la collecte réelle est exercée.
    """
    # `ModuleNotFoundError` et pas `ImportError` : c'est ce que lève un module réellement absent, et
    # c'est le seul cas que `pytest.importorskip` transforme en skip — un `ImportError` levé par un
    # module qui existe signale un module CASSÉ, que pytest fait remonter exprès. Un shim qui lève
    # le mauvais type testerait une propriété que personne ne rencontre.
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "yaml.py").write_text(
        'raise ModuleNotFoundError("No module named \'yaml\'", name="yaml")\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(shim)},
        encoding="utf-8",
    )
    assert proc.returncode == 0, (
        "la collecte casse sans pyyaml — un module de test l'importe en dur au lieu de "
        "`pytest.importorskip('yaml')`.\n"
        f"{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    )


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
