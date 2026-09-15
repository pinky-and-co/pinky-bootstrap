"""mypy hermetic additional_dependencies auto-derivation.

The mypy
hook's `additional_dependencies` is derived from the TARGET repo's own pyproject.toml runtime
`dependencies` — mypy pin + every real dependency, `pinky-*` included (all public on PyPI).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup


PYPROJECT = """
[project]
name = "x"
dependencies = [
    "snowflake>=1.12.0",
    "pinky-core>=0.1.0",
    "pinky-snowpark>=0.1.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest", "mypy"]
"""


def test_mypy_additional_dependencies_includes_pinky_deps(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    deps = setup.mypy_additional_dependencies(tmp_path)
    assert deps[0] == f"mypy=={setup.MYPY_PIN}"
    assert "snowflake>=1.12.0" in deps
    assert "pydantic>=2.0" in deps
    assert "pinky-core>=0.1.0" in deps
    assert "pinky-snowpark>=0.1.0" in deps


def test_mypy_additional_dependencies_ignores_optional_deps(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    deps = setup.mypy_additional_dependencies(tmp_path)
    assert "pytest" not in deps


def test_mypy_additional_dependencies_empty_repo_is_pin_only(tmp_path):
    assert setup.mypy_additional_dependencies(tmp_path) == [f"mypy=={setup.MYPY_PIN}"]


def test_build_precommit_config_substitutes_mypy_placeholder(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    cfg = setup.build_precommit_config(tmp_path, ["python"])
    assert setup.MYPY_DEPS_PLACEHOLDER not in cfg
    assert '"snowflake>=1.12.0"' in cfg
    assert "language: python" in cfg
    assert '"pinky-core>=0.1.0"' in cfg


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
