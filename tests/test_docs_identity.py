"""docs_identity.json is a pure function of the engine version and the suite identity.

It carries no value that changes with every commit of pinky-bootstrap: such a field made each
commit rewrite the file in every repo, and nothing read it back.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


def test_docs_identity_is_the_engine_version_plus_the_suite_identity():
    expected = {
        "engine_version": setup.engine_version(),
        **json.loads(IDENTITY.to_json()),
    }
    assert setup.precommit.render_docs_identity(IDENTITY) == (
        json.dumps(expected, indent=2) + "\n"
    )


def test_docs_identity_does_not_pin_a_source_commit():
    rendered = json.loads(setup.precommit.render_docs_identity(IDENTITY))
    assert "engine_commit" not in rendered
    assert not hasattr(setup.precommit, "engine_commit")
