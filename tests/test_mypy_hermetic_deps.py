"""mypy hermetic additional_dependencies auto-derivation (ADR-0026).

Defines "done" for the chantier-0001 card `mypy-hermetique-deps-auto-derivees-adr0026`: the mypy
hook's `additional_dependencies` is derived from the TARGET repo's own pyproject.toml runtime
`dependencies` — mypy pin + real third-party deps, minus internal `pinky-*` packages.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


@pytest.fixture(autouse=True)
def _pin_internal_dep_prefix(monkeypatch):
    """Pin `INTERNAL_DEP_PREFIX` instead of inheriting the author's machine config.

    Its real source is `.pinky/config.txt` — a GITIGNORED per-machine file, absent from
    any CI checkout, where the value degrades to None (no filtering) and these assertions would
    fail. A unit test must exercise the filtering logic, never the author's local configuration.
    """
    monkeypatch.setattr(setup.precommit, "INTERNAL_DEP_PREFIX", "pinky-")


PYPROJECT = """
[project]
name = "x"
dependencies = [
    "snowflake>=1.12.0",
    "pinky-core>=0.1.0.dev2",  # pre-release, not on PyPI
    "pinky-snowpark>=0.1.0.dev1",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest", "mypy"]
"""


def test_mypy_additional_dependencies_excludes_internal_pinky_deps(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    deps = setup.mypy_additional_dependencies(tmp_path)
    assert deps[0] == f"mypy=={setup.MYPY_PIN}"
    assert "snowflake>=1.12.0" in deps
    assert "pydantic>=2.0" in deps
    assert not any(d.startswith("pinky-") for d in deps)


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
    # No internal pinky-* dep leaks into mypy additional_dependencies (pip can't install them in the
    # hermetic venv). Match the QUOTED dependency form, not a bare substring — python.yaml carries a
    # legitimate `# pinky-core:` comment (a require_serial rationale) that isn't a dependency.
    assert '"pinky-core' not in cfg


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
