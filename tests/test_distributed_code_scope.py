"""Distributed code is linted at its source: the repos that receive it neither lint nor format it."""

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
from setup.common import CORE_PRECOMMIT_DIR

TEMPLATE = CORE_PRECOMMIT_DIR / "hooks-ruff.toml"
SCOPED_HOOKS = ("ruff-check", "ruff-format", "check-narrative-comments")
IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


@pytest.mark.parametrize("extras", [["python"], ["python-lint"]])
def test_linters_skip_the_distributed_hooks(tmp_path, extras):
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load(setup.build_precommit_config(tmp_path, extras))
    hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
    assert {pcid: hooks[pcid].get("exclude") for pcid in SCOPED_HOOKS} == {
        pcid: "^scripts/hooks/" for pcid in SCOPED_HOOKS
    }


def test_the_distributed_ruff_config_turns_every_rule_off():
    config = tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert config == {"lint": {"select": []}, "format": {"exclude": ["*.py"]}}


def test_distribute_drops_the_ruff_config_into_scripts_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.precommit, "_prek_install", lambda *_a, **_k: None)
    monkeypatch.setattr(
        setup.precommit, "_ensure_secrets_baseline", lambda *_a, **_k: None
    )
    repo = tmp_path / "pinky-thing"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'thing'\nversion = '0'\n", encoding="utf-8"
    )
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY)
    assert (repo / "scripts" / "hooks" / "ruff.toml").read_text(
        encoding="utf-8"
    ) == TEMPLATE.read_text(encoding="utf-8")
