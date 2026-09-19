"""One workflow file per concern: `ci.yml` is the same for every repo, what is specific goes in its own.

`on.push.paths` filters a workflow as a whole, so a job that needs other triggers than the tests
(the Worker deploy) cannot live in `ci.yml`: with only `pyproject.toml` and `.github/**` listed, a push
that touches just the Worker starts nothing and the deploy silently never runs. Each specific
concern (Worker, Windows gate, install walkthrough) is a workflow of its own, with its own `on`.
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
from setup import precommit

IDENTITY = setup.SuiteIdentity(
    header_image_url="https://example.test/header.png",
    header_alt="pinky",
    suite_line="Part of the pinky suite.",
    github_org="pinky-test",
    pitch_heading="Why x",
    pitch_paragraphs=("x",),
    pitch_pills=("x",),
)


def _repo(tmp_path: Path, name: str = "some-repo", *, worker: bool = False) -> Path:
    repo = tmp_path / name
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    if worker:
        (repo / "wrangler.jsonc").write_text(
            '{ "d1_databases": [ { "binding": "DB", "database_name": "pilot-sandbox" } ] }',
            encoding="utf-8",
        )
    return repo


def _text(rendered: str | None) -> str:
    assert rendered is not None
    return rendered


def _workflow_name(text: str) -> str:
    match = re.search(r"^name: (.+)$", text, re.M)
    assert match
    return match.group(1)


def _job_names(text: str) -> list[str]:
    """The top-level job names, in order."""
    return re.findall(r"^  ([a-z][\w-]*):\n", text.split("\njobs:\n", 1)[1], re.M)


def _trigger_block(text: str, event: str) -> str:
    """The lines under `on.<event>:`, up to the next event or the end of `on:`."""
    match = re.search(rf"^  {event}:\n((?:    .*\n|\n)*)", text, re.M)
    assert match, event
    return match.group(1)


def _push_paths(text: str) -> list[str]:
    return re.findall(r'^      - "(.*)"$', _trigger_block(text, "push"), re.M)


def test_ci_yml_is_identical_for_a_worker_repo_and_a_plain_one(tmp_path):
    plain = _repo(tmp_path / "a", "same-name")
    worker = _repo(tmp_path / "b", "same-name", worker=True)

    assert precommit.render_ci_yml(worker) == precommit.render_ci_yml(plain)


def test_ci_yml_carries_only_the_ci_job_everywhere(tmp_path):
    for repo in (
        _repo(tmp_path, "some-repo", worker=True),
        _repo(tmp_path, "pinky-core"),
        precommit.SCRIPT_DIR,
    ):
        assert _job_names(_text(precommit.render_ci_yml(repo))) == ["ci"]


def test_a_worker_repo_gets_a_worker_workflow_with_its_own_triggers(tmp_path):
    text = _text(precommit.render_worker_yml(_repo(tmp_path, worker=True)))

    assert _workflow_name(text) == "Worker"
    assert _job_names(text) == ["worker-bundle", "worker-deploy"]
    assert _push_paths(text) == [
        "pyproject.toml",
        ".github/**",
        "src/**",
        "wrangler.jsonc",
        "migrations/**",
    ]
    # the tests' door stays the PR, on every path: a required check never waits on a filter
    assert "paths" not in _trigger_block(text, "pull_request")


def test_the_worker_workflow_is_the_template_filled_with_the_repos_real_values(
    tmp_path,
):
    expected = (
        precommit.CI_WORKER_TPL_PATH.read_text(encoding="utf-8")
        .replace(precommit.CI_PYTHON_VERSION_PLACEHOLDER, "3.12")
        .replace(precommit.CI_INSTALL_CMD_PLACEHOLDER, precommit.CI_DEFAULT_INSTALL_CMD)
        .replace(precommit.CI_TESTS_CMD_PLACEHOLDER, precommit.CI_DEFAULT_TESTS_CMD)
        .replace(precommit.CI_D1_DATABASE_PLACEHOLDER, "pilot-sandbox")
    )

    assert precommit.render_worker_yml(_repo(tmp_path, worker=True)) == expected


def test_a_repo_without_a_worker_gets_no_worker_workflow(tmp_path):
    assert precommit.render_worker_yml(_repo(tmp_path)) is None


def test_the_windows_gate_is_its_own_workflow_and_only_the_engine_carries_it(tmp_path):
    """The gate proves the distributed hooks run on Windows; the engine, which ships them, is the
    one witness — a lib such as `pinky-core` does not need its own."""
    text = _text(precommit.render_windows_yml(_repo(tmp_path, "pinky-bootstrap")))

    assert _workflow_name(text) == "Windows"
    assert _job_names(text) == ["precommit-windows"]
    assert precommit.render_windows_yml(_repo(tmp_path, "pinky-core")) is None


def test_the_install_walkthrough_is_its_own_workflow_for_the_engine_only(tmp_path):
    text = _text(precommit.render_install_walkthrough_yml(precommit.SCRIPT_DIR))

    assert _workflow_name(text) == "Install walkthrough"
    assert _job_names(text) == ["install-walkthrough-windows"]
    assert precommit.render_install_walkthrough_yml(_repo(tmp_path, "consumer")) is None


def test_the_split_workflows_are_staged_by_a_commit_distribution():
    assert set(precommit.DISTRIBUTED_PATHS) >= {
        ".github/workflows/windows.yml",
        ".github/workflows/worker.yml",
        ".github/workflows/install-walkthrough.yml",
    }


def test_distributing_a_worker_repo_writes_worker_yml_and_leaves_no_drift(tmp_path):
    repo = _repo(tmp_path, "pinky-worker", worker=True)
    setup._init_repo_skeleton(repo)

    setup.distribute(repo, dry_run=False, identity=IDENTITY)

    workflows = repo / ".github" / "workflows"
    assert sorted(p.name for p in workflows.glob("*.yml")) == [
        "ci.yml",
        "prek.yml",
        "worker.yml",
    ]
    assert setup.check_drift([repo], None) == 0


def test_a_ci_yml_from_the_old_layout_is_rewritten_and_worker_yml_added(tmp_path):
    """Migration: a Worker repo distributed before the split has the worker jobs inside `ci.yml`.
    One distribution moves them out — same job names, so nothing that requires them changes."""
    repo = _repo(tmp_path, "pinky-worker", worker=True)
    setup._init_repo_skeleton(repo)
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\non: push\njobs:\n  ci: {}\n  worker-bundle: {}\n  worker-deploy: {}\n",
        encoding="utf-8",
    )

    setup.distribute(repo, dry_run=False, identity=IDENTITY)

    assert _job_names((workflows / "ci.yml").read_text(encoding="utf-8")) == ["ci"]
    assert (workflows / "worker.yml").is_file()


@pytest.mark.parametrize("name", ["ci.yml", "windows.yml", "worker.yml"])
def test_a_generated_workflow_says_so(name, tmp_path):
    """A file `pinky` writes is overwritten on every distribution: say it at the top, where the
    next hand-edit would happen."""
    repo = _repo(tmp_path, "pinky-bootstrap", worker=True)
    render = {
        "ci.yml": precommit.render_ci_yml,
        "windows.yml": precommit.render_windows_yml,
        "worker.yml": precommit.render_worker_yml,
    }[name]

    text = render(repo)

    assert text is not None
    assert text.splitlines()[0].startswith("# Generated by pinky")


def test_the_walkthrough_distributes_without_a_prompt():
    """CI has no terminal: since `distribute` asks before it writes, the real distribution the
    walkthrough plays must pass `--yes`, or it refuses and the job fails."""
    template = precommit.CI_INSTALL_WALKTHROUGH_TPL_PATH.read_text(encoding="utf-8")

    assert "pinky repo distribute --repo pinky-demo-repo --yes" in template


def _events(text: str) -> list[str]:
    """The events under `on:`, in order."""
    on_block = text.split("\non:\n", 1)[1].split("\njobs:\n", 1)[0]
    return re.findall(r"^  ([a-z_]+):", on_block, re.M)


def test_the_windows_workflows_do_not_run_on_pull_requests(tmp_path):
    """They are the expensive jobs and prove nothing a Linux run does not: on `main` after the merge,
    or by hand, not on every push of every PR."""
    windows = _text(precommit.render_windows_yml(_repo(tmp_path, "pinky-bootstrap")))
    walkthrough = _text(precommit.render_install_walkthrough_yml(precommit.SCRIPT_DIR))

    assert _events(windows) == ["push", "workflow_dispatch"]
    assert _events(walkthrough) == ["push", "workflow_dispatch"]


def test_the_windows_workflows_run_on_main_only_and_skip_documentation(tmp_path):
    windows = _text(precommit.render_windows_yml(_repo(tmp_path, "pinky-bootstrap")))

    assert re.search(r"^    branches: \[main\]$", _trigger_block(windows, "push"), re.M)
    assert re.findall(r'^      - "(.*)"$', _trigger_block(windows, "push"), re.M) == [
        "**.md",
        "docs/**",
    ]
