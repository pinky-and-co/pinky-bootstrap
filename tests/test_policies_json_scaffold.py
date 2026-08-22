"""`distribute()` scaffolds `.claude/policies.json` with `branch_workflow: null`.

No key gets a real default value: `branch_workflow` has no safe universal one
(verified across the parc — "git flow" on some repos, "github flow" on others),
so writing one would assert a possibly wrong governance fact. `null` names the
expected key as visibly unset rather than silently absent; a human fills in the
value.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

IDENTITY = setup.SuiteIdentity(
    header_image_url="",
    header_alt="",
    suite_line="",
    github_org="test-org",
    pitch_heading="",
    pitch_paragraphs=(),
    pitch_pills=(),
)


def test_missing_policies_json_is_scaffolded_with_null_branch_workflow(tmp_path):
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)
    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)

    policies_path = repo / ".claude" / "policies.json"
    assert policies_path.exists()
    assert policies_path.read_text(encoding="utf-8") == '{"branch_workflow": null}\n'


def test_existing_policies_json_is_never_overwritten(tmp_path):
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)
    policies_path = repo / ".claude" / "policies.json"
    policies_path.parent.mkdir(parents=True, exist_ok=True)
    original_content = '{"branch_workflow": "git flow"}'
    policies_path.write_text(original_content, encoding="utf-8")

    setup.distribute(repo, dry_run=False, identity=IDENTITY, selected_hooks=None)

    assert policies_path.read_text(encoding="utf-8") == original_content


def test_dry_run_does_not_write_policies_json(tmp_path):
    repo = tmp_path / "pinky-thing"
    setup._init_repo_skeleton(repo)

    setup.distribute(repo, dry_run=True, identity=IDENTITY, selected_hooks=None)

    assert not (repo / ".claude" / "policies.json").exists()
