"""Oracles for `render_ci_yml`'s install/audit steps (chantier-0024, durcir-resolution-deps-ci).

`pip install -e . --group dev` ignored the committed `uv.lock` — live resolution against PyPI on
every run. Replaced by `uv sync --locked` (fails on drift instead of installing a stale lock
silently) plus a blocking `pip-audit` step, Linux job only.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod  # noqa: E402


@pytest.fixture
def lib_repo(tmp_path):
    """A repo shaped like a pinky lib with no install override."""
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    return repo


def _named_repo(tmp_path, name):
    repo = tmp_path / name
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    return repo


@pytest.fixture
def pinky_core_repo(tmp_path):
    return _named_repo(tmp_path, "pinky-core")


@pytest.fixture
def pinky_provider_repo(tmp_path):
    return _named_repo(tmp_path, "pinky-provider")


def _steps(repo, job):
    wf = yaml.safe_load(precommit_mod.render_ci_yml(repo))
    return wf["jobs"][job]["steps"]


def _step_names(steps):
    return [s.get("name") for s in steps]


def test_ci_installs_via_uv_sync_locked(lib_repo):
    steps = _steps(lib_repo, "ci")
    install = next(s for s in steps if s.get("name") == "Install dependencies")
    assert install["run"] == precommit_mod.CI_DEFAULT_INSTALL_CMD
    assert install["run"] == "uv sync --locked --no-sources --group dev"


def test_ci_sets_up_uv_before_installing(lib_repo):
    names = _step_names(_steps(lib_repo, "ci"))
    assert names.index("Install uv") < names.index("Install dependencies")
    steps = _steps(lib_repo, "ci")
    setup = next(s for s in steps if s.get("name") == "Install uv")
    assert setup["uses"] == "astral-sh/setup-uv@v6"


def test_ci_runs_pip_audit_after_install_and_it_is_blocking(lib_repo):
    steps = _steps(lib_repo, "ci")
    names = _step_names(steps)
    assert names.index("Install dependencies") < names.index("Audit dependencies")
    audit = next(s for s in steps if s.get("name") == "Audit dependencies")
    # Un `uv run pip-audit`/`uvx pip-audit` nu audite un env d'outil isolé, pas les deps du
    # projet (mesuré : ~29 paquets au lieu des ~95 réels) — l'export force le vrai arbre résolu.
    assert "uv export" in audit["run"]
    assert "--all-extras --all-groups" in audit["run"]
    assert "pip-audit -r" in audit["run"]
    assert "continue-on-error" not in audit, "pip-audit must be blocking, not advisory"


def test_precommit_windows_job_does_not_run_pip_audit(pinky_core_repo):
    names = _step_names(_steps(pinky_core_repo, "precommit-windows"))
    assert "Audit dependencies" not in names, (
        "pip-audit runs once, in the Linux `ci` job — findings do not depend on the OS"
    )


def test_precommit_windows_job_also_sets_up_uv(pinky_core_repo):
    names = _step_names(_steps(pinky_core_repo, "precommit-windows"))
    assert "Install uv" in names


def test_pinky_core_override_keeps_extras_via_uv_sync(pinky_core_repo):
    install = next(
        s
        for s in _steps(pinky_core_repo, "ci")
        if s.get("name") == "Install dependencies"
    )
    assert install["run"] == (
        "uv sync --locked --extra validate --extra address --extra schedule --extra xml "
        "--extra lint --group dev"
    )


def test_pinky_provider_override_uses_prerelease_allow_and_drops_locked(
    pinky_provider_repo,
):
    # pinky-provider is in CI_NO_LOCK_REPOS ([tool.uv.sources] -> sibling repos) — --locked
    # would permanently disagree with a lock that must also satisfy --no-sources (chantier 0024).
    install = next(
        s
        for s in _steps(pinky_provider_repo, "ci")
        if s.get("name") == "Install dependencies"
    )
    assert install["run"] == "uv sync --no-sources --prerelease allow --group dev"


def test_no_lock_repo_without_override_drops_locked_too(tmp_path):
    # Same exemption via CI_DEFAULT_INSTALL_CMD (no CI_INSTALL_OVERRIDES entry) — pinky-connect
    # is CI_NO_LOCK_REPOS but has no per-repo override.
    repo = _named_repo(tmp_path, "pinky-connect")
    install = next(
        s for s in _steps(repo, "ci") if s.get("name") == "Install dependencies"
    )
    assert install["run"] == "uv sync --no-sources --group dev"


def test_no_sources_ignored_when_repo_has_no_uv_sources_override(pinky_core_repo):
    # Trouvé en CI réelle (pinky-connect PR #8) : `[tool.uv.sources]` pointe un repo frère en
    # chemin relatif (`../pinky-core`, dev only) — `pip install` l'ignorait déjà silencieusement,
    # `uv sync` l'honore et casse en CI isolée ("Distribution not found", pas de repo voisin).
    # pinky-core lui-même n'a pas de `[tool.uv.sources]` — `--no-sources` y est un no-op, pas
    # besoin de l'exiger dans son override propre (cf `test_pinky_core_override_keeps_extras...`).
    install = next(
        s
        for s in _steps(pinky_core_repo, "ci")
        if s.get("name") == "Install dependencies"
    )
    assert "--no-sources" not in install["run"]


def test_tests_step_runs_through_uv(lib_repo):
    # Trouvé en CI réelle (pinky-core PR #27, Linux et Windows) : `uv sync --locked` installe dans
    # le venv d'uv, plus le Python système que ciblait `pip install` — un `pytest` nu sur le PATH
    # sort "command not found" / "not recognized". `uv run` expose le bin du venv.
    steps = _steps(lib_repo, "ci")
    tests_step = next(s for s in steps if s.get("name") == "Tests")
    assert tests_step["run"] == "uv run pytest"


def test_windows_tests_step_also_runs_through_uv(pinky_core_repo):
    steps = _steps(pinky_core_repo, "precommit-windows")
    tests_step = next(s for s in steps if s.get("name") == "Tests")
    assert tests_step["run"] == "uv run pytest"


def test_no_repo_install_step_still_calls_pip_install(
    lib_repo, pinky_core_repo, pinky_provider_repo
):
    for repo in (lib_repo, pinky_core_repo, pinky_provider_repo):
        install = next(
            s for s in _steps(repo, "ci") if s.get("name") == "Install dependencies"
        )
        assert "pip install" not in install["run"]
