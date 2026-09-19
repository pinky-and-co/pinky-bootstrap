"""Oracles for `render_prek_yml` — the server-side hook suite of the NON-lib repos.

Some repos ran the hook suite only through the LOCAL pre-commit — a net that
disappears the moment a `--no-verify` passes or a machine has no hooks installed. One of them,
`_corpus-pinky`, had no governance at all: no `.pre-commit-config.yaml`, no git hook, no CI. The
libs were fine, because their `ci.yml` already runs `prek run --all-files` as its first step.

The contract this file pins is therefore **complementarity**, not the file's contents: for any repo
the distribution touches, the hook suite must run server-side through exactly ONE of the two
workflows — never both (duplicate CI minutes, two places to keep in sync), never neither (that is
the hole this whole change closes). That invariant is what a future refactor of either renderer can
silently break; the YAML equality check below only guards the emitted text.

Note for whoever extends this file: `render_ci_yml`'s dependency-install/audit steps are covered in
`test_ci_yml_dependency_install.py`, not here — its trigger/hook-suite properties below remain the
only `render_ci_yml` oracles in this file.
"""

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod  # noqa: E402


@pytest.fixture
def lib_repo(tmp_path):
    """A repo shaped like a pinky lib: a pyproject with a derivable requires-python."""
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    return repo


@pytest.fixture
def non_lib_repo(tmp_path):
    """A repo with no pyproject — studio / infra / assets / corpus shape."""
    repo = tmp_path / "_corpus-fake"
    repo.mkdir()
    return repo


def test_prek_lands_on_every_repo_and_ci_only_where_there_is_a_package(
    lib_repo, non_lib_repo
):
    """Le partage se fait par SUJET, plus par fichier.

    Avant : les deux renderers étaient exclusifs — la lib faisait tourner les hooks dans son ci.yml,
    donc elle ne recevait pas prek.yml. Le partage était par fichier, et il a coûté le second job de
    prek.yml : `pr-required-on-main`, le SEUL garde-fou serveur contre un push direct sur `main`
    (la protection de branche GitHub est payante sur du privé, et aucune des deux orgs ne l'a) —
    perdu sans que rien ne le signale.

    Args:
        lib_repo: Repo avec un pin Python dérivable.
        non_lib_repo: Repo sans.
    """
    for repo in (lib_repo, non_lib_repo):
        assert precommit_mod.render_prek_yml(repo), (
            f"{repo.name}: prek.yml est universel — hygiène et convention de branche"
        )
    assert precommit_mod.render_ci_yml(lib_repo) is not None
    assert precommit_mod.render_ci_yml(non_lib_repo) is None, (
        "sans paquet à tester, un ci.yml n'a pas de cible"
    )


def test_the_branch_guard_reaches_every_repo(lib_repo, non_lib_repo):
    """Le garde lui-même, pas seulement le fichier qui le porte — c'est ça qui manquait."""
    for repo in (lib_repo, non_lib_repo):
        assert "pr-required-on-main" in precommit_mod.render_prek_yml(repo)


def test_ci_yml_no_longer_runs_the_hook_suite(lib_repo):
    """Cliquet anti-doublon : les hooks ont UNE source, prek.yml.

    Les réintroduire dans ci.yml ferait tourner la suite deux fois par push sur chaque lib — le
    doublon qu'on vient de supprimer. Le job `precommit-windows` est exclu du contrôle : il exerce
    délibérément un hook SOUS WINDOWS, ce n'est pas la suite serveur.
    """
    import yaml

    ci = yaml.safe_load(precommit_mod.render_ci_yml(lib_repo))
    steps = ci["jobs"]["ci"]["steps"]
    offenders = [s for s in steps if "prek" in str(s.get("uses", "")).lower()]

    assert not offenders, f"ci.yml relance les hooks : {offenders}"


def test_ci_yml_push_trigger_is_narrowed_to_what_can_break_the_tests(lib_repo):
    """`pull_request` teste déjà l'arbre FUSIONNÉ, donc le push d'après est une redite — 32 des
    60 derniers runs, 53 % du budget. Le push survit sur les deux seuls chemins que `branch.md`
    autorise en direct sur `develop` et qui peuvent réellement casser la suite.
    """
    import yaml

    triggers = yaml.safe_load(precommit_mod.render_ci_yml(lib_repo))[True]

    assert set(triggers["push"]["paths"]) == {"pyproject.toml", ".github/**"}
    assert "paths" not in triggers["pull_request"], (
        "une PR doit tout tester, jamais un sous-ensemble de chemins"
    )


def test_prek_runs_the_hooks_on_the_repo_own_python_pin(lib_repo, non_lib_repo):
    """Le gabarit fige 3.12 dans son texte — correct tant qu'il n'allait qu'à des repos sans pin.

    Maintenant qu'il part aussi chez les libs, il doit suivre la version qu'elles déclarent : ruff
    et mypy ne se comportent pas à l'identique d'une mineure à l'autre.
    """
    (lib_repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.13"\n', encoding="utf-8"
    )

    assert '"3.13"' in precommit_mod.render_prek_yml(lib_repo)
    assert '"3.12"' in precommit_mod.render_prek_yml(non_lib_repo)


def test_prek_yml_is_whole_output_equal_to_the_template(non_lib_repo):
    """Equality on the entire emitted file, for a repo with no Python pin to substitute.

    Args:
        non_lib_repo: Repo without a pyproject.
    """
    expected = precommit_mod.PREK_TPL_PATH.read_text(encoding="utf-8")
    assert precommit_mod.render_prek_yml(non_lib_repo) == expected


def test_prek_yml_satisfies_the_github_actions_grammar(non_lib_repo):
    """Parse the emitted workflow and check it against GitHub's documented schema.

    A workflow GitHub refuses to load is silently never run — the exact failure mode this net
    exists to prevent. Verified against the tool's grammar, not a snapshot of today's output.

    Args:
        non_lib_repo: Repo without a pyproject.
    """
    wf = yaml.safe_load(precommit_mod.render_prek_yml(non_lib_repo))

    triggers = wf.get("on", wf.get(True))
    assert triggers is not None, "workflow declares no trigger"
    assert set(triggers) == {"push", "pull_request"}

    assert wf["jobs"], "workflow declares no job"
    for name, job in wf["jobs"].items():
        assert "runs-on" in job, f"job {name}: no runner"
        assert job["steps"], f"job {name}: no step"
        assert job["permissions"], f"job {name}: no permissions block"
        assert set(job["permissions"].values()) <= {"read", "none"}, (
            f"job {name}: non-read permission — {job['permissions']}"
        )

    assert wf["jobs"]["hooks"]["permissions"] == {"contents": "read"}


def test_prek_yml_actually_runs_the_hook_suite(non_lib_repo):
    """The workflow is worthless if it does not invoke prek — pin that it does.

    Args:
        non_lib_repo: Repo without a pyproject.
    """
    wf = yaml.safe_load(precommit_mod.render_prek_yml(non_lib_repo))
    steps = [s for job in wf["jobs"].values() for s in job["steps"]]
    assert any("prek-action" in str(s.get("uses", "")) for s in steps)


@pytest.fixture
def plugin_repo(tmp_path):
    """A repo shaped like a Claude Code plugin repo: a `.claude-plugin/` marketplace dir."""
    repo = tmp_path / "pc-fake"
    (repo / ".claude-plugin").mkdir(parents=True)
    return repo


def test_plugin_repo_gets_claude_cli_setup(plugin_repo):
    """`validate-plugins-strict` (plugin-repo extra) shells out to `claude` — absent from the
    runner image by default (measured: exit 1, `claude` CLI not found on PATH)."""
    text = precommit_mod.render_prek_yml(plugin_repo)
    assert "npm install -g @anthropic-ai/claude-code" in text
    assert "actions/setup-node" in text


def test_non_plugin_repo_has_no_claude_cli_setup(non_lib_repo):
    """The Node.js toolchain is dead weight for the 90% of repos with no `validate-plugins-strict`."""
    assert "claude-code" not in precommit_mod.render_prek_yml(non_lib_repo)


def test_plugin_repo_prek_yml_still_valid_yaml_with_claude_cli_step(plugin_repo):
    wf = yaml.safe_load(precommit_mod.render_prek_yml(plugin_repo))
    steps = wf["jobs"]["hooks"]["steps"]
    names = [s.get("name", s.get("uses", "")) for s in steps]
    assert names.index("Install claude CLI") < names.index("Run pre-commit hooks"), (
        "claude must be on PATH before prek runs validate-plugins-strict"
    )


def test_install_walkthrough_job_only_lands_on_the_engine(tmp_path):
    """Le job installe le moteur et lance ses sous-commandes : hors du moteur, il ne peut pas passer.

    Gaté par IDENTITÉ (`repo.resolve() == SCRIPT_DIR.resolve()`), le même axe que
    `workspace-self.yaml`, et pas par un nom ajouté à `CI_WINDOWS_PILOT` — cette liste-là est un
    littéral d'instance dans le moteur, la classe de défaut qu'on cherche à retirer.

    Sans ce test, l'erreur ne se verrait qu'en rouge sur les repos consommateurs, après distribution.
    """
    import yaml

    consumer = tmp_path / "pinky-consommateur"
    consumer.mkdir()
    (consumer / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )

    engine_jobs = yaml.safe_load(precommit_mod.render_ci_yml(precommit_mod.SCRIPT_DIR))[
        "jobs"
    ]
    consumer_jobs = yaml.safe_load(precommit_mod.render_ci_yml(consumer))["jobs"]

    assert "install-walkthrough-windows" in engine_jobs
    assert "install-walkthrough-windows" not in consumer_jobs


def test_install_walkthrough_covers_the_real_sequence(tmp_path):
    """Le job doit couvrir `bootstrap (*.code-workspace) → distribute → drift` — la séquence qu'un
    adoptant joue.

    La vérification du lanceur (`py -3` dans `.claude/settings.json`) a été retirée avec
    le moteur de rendu CLAUDE.md : `distribute()` ne touche plus `.claude/`, rien à figer.
    """
    fragment = (
        precommit_mod.CORE_CI_DIR / "windows-install-walkthrough.yml.tpl"
    ).read_text(encoding="utf-8")

    assert ".code-workspace" in fragment
    assert "pinky repo distribute" in fragment
    assert "pinky repo drift" in fragment
