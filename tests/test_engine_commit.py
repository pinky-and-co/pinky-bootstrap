"""docs_identity.json pins the exact pinky-bootstrap commit a repo was distributed from."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
from setup.common import SCRIPT_DIR

IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


def test_docs_identity_records_the_engine_commit(monkeypatch):
    monkeypatch.setattr(setup.precommit, "engine_commit", lambda: "a" * 40)
    expected = {
        "engine_version": setup.engine_version(),
        "engine_commit": "a" * 40,
        **json.loads(IDENTITY.to_json()),
    }
    assert setup.precommit.render_docs_identity(IDENTITY) == (
        json.dumps(expected, indent=2) + "\n"
    )


def test_docs_identity_omits_an_unknown_engine_commit(monkeypatch):
    monkeypatch.setattr(setup.precommit, "engine_commit", lambda: None)
    expected = {
        "engine_version": setup.engine_version(),
        **json.loads(IDENTITY.to_json()),
    }
    assert setup.precommit.render_docs_identity(IDENTITY) == (
        json.dumps(expected, indent=2) + "\n"
    )


def test_engine_commit_is_the_checkout_head():
    head = subprocess.run(
        ["git", "-C", str(SCRIPT_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    commit = setup.precommit.engine_commit()
    assert commit is not None
    assert commit.removesuffix("-dirty") == head


def test_engine_commit_is_computed_once_per_run(monkeypatch):
    calls = []
    real_run = subprocess.run

    def counting_run(*args, **kwargs):
        calls.append(args)
        return real_run(*args, **kwargs)

    setup.precommit.engine_commit.cache_clear()
    monkeypatch.setattr(setup.precommit.subprocess, "run", counting_run)
    first = setup.precommit.engine_commit()
    assert setup.precommit.engine_commit() == first
    assert len(calls) == 1
