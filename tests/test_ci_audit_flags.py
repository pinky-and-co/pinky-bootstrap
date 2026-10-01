"""Oracles for the `Audit dependencies` flags `render_ci_yml` derives from the target repo.

pip re-resolves package bounds and rejects a uv `override-dependencies`, so the audit only passes
with `--disable-pip --no-deps` in a repo that declares one — and only there.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import precommit as precommit_mod  # noqa: E402

PROJECT = '[project]\nname = "pinky-fake"\nrequires-python = ">=3.12"\n'

COMMENT_LAST_LINE = "        # log de plus, ignoré comme tout log jusqu'à l'incident.\n"
EXPORT_LINE = (
    "          uv export --frozen --all-extras --all-groups --format requirements-txt "
    "--no-hashes -o /tmp/pip-audit-requirements.txt\n"
)
FLAG_COMMENT = (
    "        # --disable-pip --no-deps : l'export est entièrement épinglé, on audite le lock "
    "tel quel.\n"
    "        # pip re-résoudrait les bornes des paquets et rejetterait un `override-dependencies` "
    "d'uv.\n"
)
PLAIN_AUDIT = "          uvx pip-audit -r /tmp/pip-audit-requirements.txt\n"
FLAGGED_AUDIT = "          uvx pip-audit --disable-pip --no-deps -r /tmp/pip-audit-requirements.txt\n"


def _repo(tmp_path: Path, pyproject_tail: str) -> Path:
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(PROJECT + pyproject_tail, encoding="utf-8")
    return repo


def _audit_block(rendered: str) -> str:
    """From the last line of the audit comment to the line before the next step."""
    start = rendered.index(COMMENT_LAST_LINE)
    end = rendered.index("      - name: Tests")
    return rendered[start:end]


def test_override_dependencies_flags_the_audit(tmp_path):
    repo = _repo(
        tmp_path,
        '\n[tool.uv]\noverride-dependencies = ["cryptography>=50.0.0"]\n',
    )
    rendered = precommit_mod.render_ci_yml(repo)
    assert _audit_block(rendered) == (
        COMMENT_LAST_LINE
        + FLAG_COMMENT
        + "        run: |\n"
        + EXPORT_LINE
        + FLAGGED_AUDIT
        + "\n"
    )


@pytest.mark.parametrize(
    "tail",
    [
        "",
        '\n[tool.uv]\nrequired-version = ">=0.9.17"\n',
        "\n[tool.uv]\noverride-dependencies = []\n",
        '\n[tool.uv.sources]\nfoo = { path = "../foo" }\n',
    ],
    ids=["no-tool-uv", "tool-uv-without-key", "empty-list", "sources-only"],
)
def test_no_override_leaves_the_audit_plain(tmp_path, tail):
    rendered = precommit_mod.render_ci_yml(_repo(tmp_path, tail))
    assert _audit_block(rendered) == (
        COMMENT_LAST_LINE + "        run: |\n" + EXPORT_LINE + PLAIN_AUDIT + "\n"
    )
    assert "--disable-pip" not in rendered
    assert "--no-deps" not in rendered
    assert "__AUDIT_FLAGS_COMMENT__" not in rendered
    assert "__AUDIT_FLAGS__" not in rendered


def test_invalid_pyproject_means_no_flags(tmp_path):
    repo = tmp_path / "pinky-fake"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[tool.uv\noverride-dependencies = ["cryptography>=50.0.0"]\n', encoding="utf-8"
    )
    assert precommit_mod._uv_overrides_dependencies(repo) is False


def test_missing_pyproject_means_no_flags(tmp_path):
    assert precommit_mod._uv_overrides_dependencies(tmp_path) is False


def test_other_templates_carry_no_audit_placeholder():
    """They go through the same renderer: a placeholder they do not carry stays a no-op."""
    for template in (
        precommit_mod.CI_WINDOWS_TPL_PATH,
        precommit_mod.CI_INSTALL_WALKTHROUGH_TPL_PATH,
        precommit_mod.CI_WORKER_TPL_PATH,
    ):
        assert "__AUDIT_FLAGS" not in template.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("pyproject", "expected"),
    [
        ('[tool.uv]\noverride-dependencies = "a>=1"\n', False),
        ('[tool.uv]\noverride-dependencies = { a = "b" }\n', False),
        ("[tool.uv]\noverride-dependencies = 3\n", False),
        ('tool = "x"\n', False),
        ('[tool]\nuv = "x"\n', False),
        ('[tool]\nuv.override-dependencies = ["a>=1"]\n', True),
        ('tool = { uv = { override-dependencies = ["a>=1"] } }\n', True),
    ],
    ids=[
        "string",
        "inline-table",
        "number",
        "tool-not-a-table",
        "uv-not-a-table",
        "dotted-key",
        "inline-tables",
    ],
)
def test_uv_overrides_dependencies_shapes(tmp_path, pyproject, expected):
    (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    assert precommit_mod._uv_overrides_dependencies(tmp_path) is expected
