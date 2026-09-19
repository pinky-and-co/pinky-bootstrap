"""`distribute` shows what it would overwrite before it overwrites, and asks.

It used to write every file it owns without saying what changed, so a hand edit and a stale copy
were erased alike and nothing told the owner (a Worker repo lost its deploy triggers that way). Now a
plan pass records, for each file, what is there and what it would become; nothing is written until
the plan has been shown and confirmed.
"""

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


def _repo(tmp_path: Path, name: str = "pinky-thing") -> Path:
    repo = tmp_path / name
    setup._init_repo_skeleton(repo)
    return repo


def _plan(repo: Path) -> list[precommit.PlannedWrite]:
    plan: list[precommit.PlannedWrite] = []
    setup.distribute(repo, dry_run=True, identity=IDENTITY, plan=plan)
    return plan


def test_a_plan_pass_writes_nothing_and_records_what_it_would_write(tmp_path):
    repo = _repo(tmp_path)

    plan = _plan(repo)

    assert ".pre-commit-config.yaml" in {w.rel for w in plan}
    assert not (repo / ".pre-commit-config.yaml").exists()
    assert not (repo / "scripts").exists()


def test_a_new_file_has_no_old_content(tmp_path):
    plan = {w.rel: w for w in _plan(_repo(tmp_path))}

    assert plan[".gitleaks.toml"].old is None
    assert plan[".gitleaks.toml"].new


def test_a_repo_already_distributed_has_an_empty_plan(tmp_path):
    repo = _repo(tmp_path)
    setup.distribute(repo, dry_run=False, identity=IDENTITY)

    assert _plan(repo) == []


def test_a_hand_edited_file_shows_up_with_both_contents(tmp_path):
    repo = _repo(tmp_path)
    setup.distribute(repo, dry_run=False, identity=IDENTITY)
    config = repo / ".gitleaks.toml"
    generated = config.read_bytes()
    config.write_bytes(generated + b"# my own rule\n")

    [change] = _plan(repo)

    assert change.rel == ".gitleaks.toml"
    assert change.old == generated + b"# my own rule\n"
    assert change.new == generated


def test_a_plan_names_the_repo_of_each_change(tmp_path):
    plan = _plan(_repo(tmp_path, "pinky-named"))

    assert {w.repo for w in plan} == {"pinky-named"}


def test_the_plan_is_shown_as_a_diff_and_new_files_as_one_line():
    plan = [
        precommit.PlannedWrite("repo-a", "new.txt", None, b"a\nb\nc\n"),
        precommit.PlannedWrite(
            "repo-a", "ci.yml", b"one\ntwo\nthree\n", b"one\nTWO\nthree\n"
        ),
        precommit.PlannedWrite("repo-b", "x.toml", b"k = 1\n", b"k = 2\n"),
    ]

    assert precommit.format_plan(plan) == (
        "→ repo-a\n"
        "  + new.txt (new file, 3 lines)\n"
        "  ~ ci.yml\n"
        "    @@ -1,3 +1,3 @@\n"
        "     one\n"
        "    -two\n"
        "    +TWO\n"
        "     three\n"
        "\n"
        "→ repo-b\n"
        "  ~ x.toml\n"
        "    @@ -1 +1 @@\n"
        "    -k = 1\n"
        "    +k = 2\n"
        "\n"
        "3 files change in 2 repos"
    )


def test_a_framework_owned_hook_is_one_line_with_its_counts_not_a_diff():
    """`scripts/hooks/` is a verbatim copy nobody edits: a diff of it is noise that buries the files
    a person may have changed (workflows, config, pyproject)."""
    plan = [
        precommit.PlannedWrite(
            "r", "scripts/hooks/check_zws.py", b"a\nb\nc\n", b"a\nB\nc\nd\n"
        ),
        precommit.PlannedWrite("r", "ci.yml", b"x\n", b"y\n"),
    ]

    assert precommit.format_plan(plan) == (
        "→ r\n"
        "  ~ scripts/hooks/check_zws.py (+2 −1 lines)\n"
        "  ~ ci.yml\n"
        "    @@ -1 +1 @@\n"
        "    -x\n"
        "    +y\n"
        "\n"
        "2 files change in 1 repo"
    )


def test_a_long_diff_is_cut_with_a_count_of_what_is_hidden():
    old = "".join(f"line {i}\n" for i in range(100)).encode()
    new = "".join(f"LINE {i}\n" for i in range(100)).encode()

    report = precommit.format_plan([precommit.PlannedWrite("r", "big.txt", old, new)])

    assert "… " in report
    assert report.count("\n") < 60


def test_an_empty_plan_says_everything_is_up_to_date():
    assert precommit.format_plan([]) == "Every repo is up to date."


def test_yes_applies_without_asking():
    def ask(prompt: str) -> str:
        raise AssertionError("must not ask")

    assert (
        precommit.confirm_distribution(3, 2, yes=True, interactive=False, ask=ask)
        is True
    )


def test_an_answer_of_y_applies_and_anything_else_cancels():
    assert precommit.confirm_distribution(
        3, 2, yes=False, interactive=True, ask=lambda p: "y"
    )
    assert not precommit.confirm_distribution(
        3, 2, yes=False, interactive=True, ask=lambda p: ""
    )
    assert not precommit.confirm_distribution(
        3, 2, yes=False, interactive=True, ask=lambda p: "n"
    )


def test_without_a_terminal_and_without_yes_it_refuses(capsys):
    with pytest.raises(SystemExit) as exc:
        precommit.confirm_distribution(
            3, 2, yes=False, interactive=False, ask=lambda p: "y"
        )

    assert exc.value.code == 1
    assert "pass --yes" in capsys.readouterr().err
