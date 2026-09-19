"""A Worker repo's ci.yml must start on a push that only changes the Worker.

`worker-deploy` is a job of the same workflow as the tests, and GitHub applies `on.push.paths` to the
workflow as a whole: with only `pyproject.toml` and `.github/**` listed, a push touching just `src/`,
`wrangler.jsonc` or `migrations/` starts nothing, and the deploy never runs — silently, nothing turns
red. A hand-added filter was erased by the next distribution, which is why the template carries it.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit


def _repo(tmp_path: Path, *, worker: bool) -> Path:
    repo = tmp_path / "some-repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    if worker:
        (repo / "wrangler.jsonc").write_text(
            '{ "d1_databases": [ { "binding": "DB", "database_name": "pilot-sandbox" } ] }',
            encoding="utf-8",
        )
    return repo


def _push_paths(ci_yml: str) -> list[str]:
    """The entries under `on.push.paths`, in order."""
    block = re.search(
        r"^  push:\n(?:.*\n)*?    paths:\n((?:      [-#] .*\n)+)", ci_yml, re.M
    )
    assert block, "no `on.push.paths` block"
    return re.findall(r'      - "(.*)"', block.group(1))


def _job_names(ci_yml: str) -> list[str]:
    """The top-level job names of the rendered workflow, in order."""
    jobs = ci_yml.split("\njobs:\n", 1)[1]
    return re.findall(r"^  ([a-z][\w-]*):\n", jobs, re.M)


def test_a_worker_repo_ci_starts_on_a_push_that_only_changes_the_worker(tmp_path):
    ci_yml = precommit.render_ci_yml(_repo(tmp_path, worker=True))

    assert _job_names(ci_yml) == ["ci", "worker-bundle", "worker-deploy"]
    assert _push_paths(ci_yml) == [
        "pyproject.toml",
        ".github/**",
        "src/**",
        "wrangler.jsonc",
        "migrations/**",
    ]


def test_a_repo_without_a_worker_keeps_the_narrow_push_filter(tmp_path):
    ci_yml = precommit.render_ci_yml(_repo(tmp_path, worker=False))

    assert _job_names(ci_yml) == ["ci"]
    assert _push_paths(ci_yml) == ["pyproject.toml", ".github/**"]
