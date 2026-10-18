"""Repo name in generated docs derives from the origin remote, never from the folder name.

A worker isolated in a worktree commits from `.claude/worktrees/agent-<id>/`: taking the
folder name there writes `…/agent-<id>/…` CI/PyPI badge URLs and an `agent-<id>/` tree root
into the regenerated README. The origin remote is identical from the main checkout and from
any worktree — the only stable source for the name.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
from tests.test_engine_version import IDENTITY

_spec = importlib.util.spec_from_file_location(
    "render_docs", setup.CORE_HOOKS_DIR / "render_docs.py"
)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)


def _git_repo(folder: Path, origin: str | None) -> Path:
    folder.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
    if origin:
        subprocess.run(
            ["git", "remote", "add", "origin", origin], cwd=folder, check=True
        )
    return folder


def test_repo_name_comes_from_origin_not_the_folder(tmp_path):
    """The folder is `agent-42` (a worktree name), the remote says `pinky-thing`."""
    repo = _git_repo(
        tmp_path / "agent-42", "https://github.com/pinky-and-co/pinky-thing.git"
    )
    assert rd.repo_name(repo) == "pinky-thing"


def test_repo_name_strips_the_git_suffix_of_an_ssh_remote(tmp_path):
    repo = _git_repo(tmp_path / "wt", "git@github.com:pinky-and-co/pinky-core.git")
    assert rd.repo_name(repo) == "pinky-core"


def test_repo_name_ignores_a_trailing_slash(tmp_path):
    repo = _git_repo(tmp_path / "wt", "https://github.com/pinky-and-co/pinky-thing/")
    assert rd.repo_name(repo) == "pinky-thing"


def test_repo_name_ignores_a_trailing_slash_before_the_git_suffix(tmp_path):
    repo = _git_repo(
        tmp_path / "wt", "https://github.com/pinky-and-co/pinky-thing.git/"
    )
    assert rd.repo_name(repo) == "pinky-thing"


def test_repo_name_handles_an_scp_remote_without_any_slash(tmp_path):
    """scp syntax `git@host:repo.git` — no `/`, the separator is the colon."""
    repo = _git_repo(tmp_path / "wt", "git@github.com:pinky-core.git")
    assert rd.repo_name(repo) == "pinky-core"


def test_repo_name_falls_back_to_the_folder_without_origin(tmp_path):
    """A repo not yet pushed has no other source: the folder name, and nothing else."""
    repo = _git_repo(tmp_path / "fresh-scaffold", None)
    assert rd.repo_name(repo) == "fresh-scaffold"


def test_tree_root_uses_the_origin_name(tmp_path):
    """Oracle — the whole first tree line, not a fragment: a commit made from a worktree must
    keep the repo name as the tree root, not the worktree folder's name."""
    repo = _git_repo(
        tmp_path / "agent-42", "https://github.com/pinky-and-co/pinky-thing.git"
    )
    (repo / "README.md").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    # ligne 0 = la clôture ```text, ligne 1 = la racine de l'arborescence
    assert rd.render_tree(repo).splitlines()[1] == "pinky-thing/"


def test_badge_urls_use_the_origin_name(tmp_path):
    """Oracle — the full badges section: the PyPI URL carries the origin name, and the folder
    name (`agent-42`) appears nowhere."""
    repo = _git_repo(
        tmp_path / "agent-42", "https://github.com/pinky-and-co/pinky-thing.git"
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-thing"\ndescription = "A thing."\n', encoding="utf-8"
    )
    rendered = rd.inject_readme_sections_local(
        "<!-- pinky:readme-badges:start -->\n\nold\n\n<!-- pinky:readme-badges:end -->\n",
        repo,
        IDENTITY,
    )
    badges = rendered.split("<!-- pinky:readme-badges:end -->")[0]
    assert "https://img.shields.io/pypi/v/pinky-thing)" in badges
    assert "agent-42" not in badges


def test_index_home_uses_the_origin_name(tmp_path):
    """Oracle — the WHOLE docs/index.md: the heading and every badge URL carry the origin
    name, and the worktree folder name (`agent-42`) appears nowhere."""
    repo = _git_repo(
        tmp_path / "agent-42", "https://github.com/pinky-and-co/pinky-thing.git"
    )
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "pinky-thing"\ndescription = "A thing."\n', encoding="utf-8"
    )
    assert rd.render_index_home(repo, IDENTITY) == (
        "---\n"
        "title: Home\n"
        "---\n"
        "# pinky-thing\n"
        "\n"
        '<div align="center" markdown="1">\n'
        "\n"
        '<img src="" width="380" alt="">\n'
        "\n"
        "[![PyPI](https://img.shields.io/pypi/v/pinky-thing.svg)]"
        "(https://pypi.org/project/pinky-thing/)\n"
        "![Code style](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/"
        "astral-sh/ruff/main/assets/badge/v2.json)\n"
        "\n"
        "</div>\n"
        "\n"
        "A thing.\n"
    )
