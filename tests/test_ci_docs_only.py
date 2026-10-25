"""Oracles for the docs-only detection in `ci.yml` — a PR that only touches documentation must not
run the tests, while `prek.yml` keeps running and the `ci` check still reports.

The contract is the whole PR diff against its base, not the last commit: a code commit followed by
a docs commit is still a code PR. The check must also always be REPORTED (a required `ci` that never
appears blocks the merge for ever), so the job itself is never conditional — only its steps are.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import yaml

# Oracles de logique CI rendue pour des runners Linux : la simulation elle-même (faux `gh` en
# bash, `jq`, chemins POSIX) ne prouve rien sous Windows — la CI Linux/macOS porte ces contrats.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="simulation bash/jq POSIX"
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod  # noqa: E402

# Le faux `gh` applique la VRAIE expression `--jq` du script à une charge JSON (comme `gh`).
_FAKE_GH = """#!/usr/bin/env bash
echo "$*" >> "$GH_LOG"
[ -n "${FAKE_JSON+x}" ] || exit 1
printf '%s' "$FAKE_JSON" | jq -r "$4"
"""

_HEAVY_STEPS = (
    "Set up Python",
    "Install uv",
    "Install dependencies",
    "Audit dependencies",
    "Tests",
)


@pytest.fixture
def lib_repo(tmp_path):
    """A repo shaped like a pinky lib: a pyproject with a derivable requires-python.

    Args:
        tmp_path: Pytest scratch directory.

    Returns:
        The repo path.
    """
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-fake"\nrequires-python = ">=3.12"\n', encoding="utf-8"
    )
    return repo


def _steps(repo):
    """The `ci` job's steps of the rendered workflow.

    Args:
        repo: Repo the workflow is rendered for.

    Returns:
        The list of step mappings.
    """
    return yaml.safe_load(precommit_mod.render_ci_yml(repo))["jobs"]["ci"]["steps"]


def _scope_step(repo):
    """The step that decides whether the PR is documentation only.

    Args:
        repo: Repo the workflow is rendered for.

    Returns:
        The step mapping.
    """
    return next(s for s in _steps(repo) if s.get("id") == "scope")


def _run_scope(repo, tmp_path, monkeypatch, files, event="pull_request"):
    """Run the detection script with a stub `gh`; return the `docs_only` output it wrote.

    Args:
        repo: Repo the workflow is rendered for.
        tmp_path: Scratch directory for the stub, its log and the output file.
        monkeypatch: Used to put the stub first on `PATH`.
        files: What the compare call answers (a list of paths or entries, or a dict); `None`
            makes the call fail.
        event: The GitHub event name.

    Returns:
        The value written to `docs_only`.
    """
    if shutil.which("jq") is None:
        pytest.skip("jq is needed to apply the script's --jq expression")
    stub = tmp_path / "gh"
    stub.write_text(_FAKE_GH, encoding="utf-8")
    stub.chmod(0o755)
    out = tmp_path / "github_output"
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    env = {
        **os.environ,
        "GH_LOG": str(tmp_path / "gh.log"),
        "GITHUB_OUTPUT": str(out),
        "EVENT_NAME": event,
        "BASE": "a" * 40,
        "HEAD": "b" * 40,
        "REPO": "org/repo",
    }
    if isinstance(files, dict):
        env["FAKE_JSON"] = json.dumps(files)
    elif files is not None:
        entries = [f if isinstance(f, dict) else {"filename": f} for f in files]
        env["FAKE_JSON"] = json.dumps({"files": entries})
    done = subprocess.run(
        ["bash", "-c", _scope_step(repo)["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    line = next(
        ln for ln in out.read_text(encoding="utf-8").splitlines() if "docs_only" in ln
    )
    return line.split("=", 1)[1]


@pytest.mark.parametrize(
    "files",
    [
        ["docs/how-to/x.md"],
        ["README.md", "AGENTS.md", "CLAUDE.md", "LICENSE"],
        ["docs/spec.docx", "docs/budget.xlsx", "docs/deck.pptx", "docs/schema.pdf"],
        ["docs/img/flow.png", "docs/img/flow.svg"],
        ["plugins/x/README.md", "plugins/x/docs/usage.md"],
    ],
    ids=["md", "root-files", "office", "images", "plugin-docs"],
)
def test_a_pull_request_of_documentation_only_skips_the_tests(
    files, lib_repo, tmp_path, monkeypatch
):
    """Toute la PR est de la doc : `docs_only` vaut `true`.

    Args:
        files: Files of the pull request.
        lib_repo: A pinky lib repo.
        tmp_path: Scratch directory.
        monkeypatch: Pytest monkeypatch.
    """
    assert _run_scope(lib_repo, tmp_path, monkeypatch, files) == "true"


_MOVED_OUT_OF_CODE = {
    "filename": "docs/about.txt",
    "status": "renamed",
    "previous_filename": "src/main.py",
}


@pytest.mark.parametrize(
    "files",
    [
        ["docs/x.md", "src/app.py"],
        ["docs/build.py"],
        ["docs/Makefile"],
        ["docs/notes.md.bak"],
        ["notes.md"],
        ["docs-extra/x.md"],
        ["pyproject.toml"],
        ["uv.lock"],
        [".github/workflows/ci.yml"],
        ["plugins/x/skills/y/SKILL.md"],
        [],
        None,
        {"files": None},
        [_MOVED_OUT_OF_CODE],
        [f"docs/page{n}.md" for n in range(300)],
    ],
    ids=[
        "doc-and-code",
        "script-in-docs",
        "makefile-in-docs",
        "backup-suffix",
        "root-md-not-listed",
        "docs-prefix-only",
        "pyproject",
        "lockfile",
        "workflow",
        "skill",
        "empty",
        "compare-fails",
        "files-null",
        "code-renamed-into-docs",
        "300-files",
    ],
)
def test_anything_else_runs_the_tests(files, lib_repo, tmp_path, monkeypatch):
    """Un fichier hors doc, une liste vide ou illisible, un renommage de code : les tests tournent.

    Le renommage compte : l'API ne liste que le nouveau nom, et `src/main.py` déplacé vers `docs/`
    disparaîtrait d'un contrôle fait sur ce seul nom. À 300 fichiers l'API tronque sa liste : on ne
    sait pas ce qu'on ne voit pas.

    Args:
        files: What the compare call answers, or `None` when it fails.
        lib_repo: A pinky lib repo.
        tmp_path: Scratch directory.
        monkeypatch: Pytest monkeypatch.
    """
    assert _run_scope(lib_repo, tmp_path, monkeypatch, files) == "false"


def test_a_push_always_runs_the_tests(lib_repo, tmp_path, monkeypatch):
    """Le `push` ne passe que par `pyproject.toml` et `.github/` : jamais de saut là.

    Args:
        lib_repo: A pinky lib repo.
        tmp_path: Scratch directory.
        monkeypatch: Pytest monkeypatch.
    """
    assert (
        _run_scope(lib_repo, tmp_path, monkeypatch, ["docs/x.md"], event="push")
        == "false"
    )


def test_the_job_is_never_conditional_so_the_check_always_reports(lib_repo):
    """Un `ci` requis qui ne se rapporte jamais bloque la fusion : seules les étapes sautent.

    Args:
        lib_repo: A pinky lib repo.
    """
    workflow = yaml.safe_load(precommit_mod.render_ci_yml(lib_repo))

    assert "if" not in workflow["jobs"]["ci"]
    assert "paths" not in workflow[True]["pull_request"]
    assert "paths-ignore" not in workflow[True]["pull_request"]


def test_every_heavy_step_waits_for_the_scope_decision(lib_repo):
    """Installation, audit et tests dépendent de `docs_only` ; la détection passe avant eux.

    Args:
        lib_repo: A pinky lib repo.
    """
    steps = _steps(lib_repo)
    names = [s.get("name", "") for s in steps]
    scope_at = names.index(_scope_step(lib_repo)["name"])

    for heavy in _HEAVY_STEPS:
        index = next(i for i, n in enumerate(names) if n.startswith(heavy))
        assert index > scope_at, f"{heavy} s'exécute avant la détection"
        assert steps[index]["if"] == "steps.scope.outputs.docs_only != 'true'", heavy
