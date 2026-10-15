"""Le choix de l'extra `snowflake` : champs qui classent le paquet, jamais la prose du pyproject."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup


def _repo(tmp_path: Path, pyproject: str) -> Path:
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "pyproject",
    [
        # Le faux positif mesuré sur pinky-agentic-plugins : un marqueur pytest et son commentaire.
        '[project]\nname = "x"\n\n[tool.pytest.ini_options]\n'
        "# Les tests `integration` appellent un vrai compte Snowflake\n"
        'markers = ["integration: appels sur la connexion Snowflake"]\n',
        '[project]\nname = "x"\ndescription = "Marketplace (Pinky suite, Snowflake)"\n',
    ],
)
def test_snowflake_in_prose_gives_no_extra(tmp_path, pyproject):
    assert "snowflake" not in setup.resolve_extras(_repo(tmp_path, pyproject))


@pytest.mark.parametrize(
    "pyproject",
    [
        '[project]\nname = "x"\ndependencies = ["pinky-snowpark>=0.1"]\n',
        '[project]\nname = "x"\n[project.optional-dependencies]\nsf = ["snowflake-connector-python"]\n',
        '[project]\nname = "x"\n[dependency-groups]\ndev = ["snowflake-snowpark-python"]\n',
        '[project]\nname = "x"\nkeywords = ["snowflake", "utilities"]\n',
    ],
)
def test_snowflake_in_a_classifying_field_gives_the_extra(tmp_path, pyproject):
    assert "snowflake" in setup.resolve_extras(_repo(tmp_path, pyproject))


def test_unparsable_pyproject_stays_python_without_snowflake(tmp_path):
    extras = setup.resolve_extras(_repo(tmp_path, 'dependencies = ["snowflake"\n'))
    assert extras[0] == "python"
    assert "snowflake" not in extras
