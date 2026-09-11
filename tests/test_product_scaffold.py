"""`setup.py --new-repo <name> --scaffold` — product scaffolding (chantier-0001 card
scaffolding-produit-from-zero). Separate from governance (git init + distribute(), tested in
test_new_repo.py): this lays down the docs/ Diátaxis skeleton + universal stubs. Opt-in
(`--scaffold`), idempotent (never overwrites an existing file).
"""

import argparse
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup
from setup.common import SuiteIdentity
from setup.precommit import inject_readme_sections_local


def test_scaffold_product_writes_expected_files(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    written = setup.scaffold_product(target)

    expected = {
        target / "docs" / "index.md",
        target / "CONTEXT.md",
        target / "AGENT.md",
        target / "README.md",
        target / "pyproject.toml",
        target / "LICENSE",
    }
    assert set(written) == expected
    for path in expected:
        assert path.exists()
    for sub in ("adr", "explanation", "how-to", "reference"):
        assert (target / "docs" / sub).is_dir()


def test_scaffold_product_idempotent_never_overwrites(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target)

    custom = "# hand-written, do not clobber\n"
    (target / "README.md").write_text(custom, encoding="utf-8")

    written = setup.scaffold_product(target)
    assert target / "README.md" not in written
    assert (target / "README.md").read_text(encoding="utf-8") == custom


def test_scaffold_product_pyproject_has_nonempty_description(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target)
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["description"].strip()
    assert data["project"]["requires-python"] == ">=3.12"


def test_scaffold_product_pyproject_seeds_the_cache_convention(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target)
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["ruff"]["cache-dir"] == ".cache/ruff"
    assert data["tool"]["mypy"]["cache_dir"] == ".cache/mypy"
    assert data["tool"]["pytest"]["ini_options"]["cache_dir"] == ".cache/pytest"


def test_scaffold_product_pyproject_pins_the_ruff_rule_set(tmp_path):
    for repo_type in ("lib", "data"):
        target = tmp_path / f"pinky-{repo_type}"
        target.mkdir()
        setup.scaffold_product(target, repo_type)
        data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
        assert data["tool"]["ruff"]["lint"]["select"] == ["E4", "E7", "E9", "F"]


def test_scaffold_product_readme_accepts_first_run_injection(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target)
    readme = (target / "README.md").read_text(encoding="utf-8")

    identity = SuiteIdentity(
        header_image_url="https://example.test/header.png",
        header_alt="pinky",
        suite_line="Part of the pinky suite.",
        github_org="pinky-test",
        pitch_heading="Why pinky-foo",
        pitch_paragraphs=("Why this exists.",),
        pitch_pills=("fast", "simple"),
    )
    injected = inject_readme_sections_local(
        readme, target, identity, allow_first_run=True
    )
    assert injected is not None
    assert "## Why pinky-foo" in injected
    assert re.search(r"^## Documentation[ \t]*\n", injected, flags=re.MULTILINE)
    assert re.search(r"^## License[ \t]*\n", injected, flags=re.MULTILINE)
    assert injected.index("## License") == injected.rindex("##")


def test_scaffold_product_default_type_is_lib(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    written = setup.scaffold_product(target)
    assert (target / "pyproject.toml") in written
    assert not (target / "package.json").exists()


def test_scaffold_product_data_type_declares_snowpark_and_resources_dir(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target, "data")
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert "snowflake-snowpark-python" in data["project"]["dependencies"][0]
    assert (target / "resources").is_dir()
    assert data["tool"]["ruff"]["cache-dir"] == ".cache/ruff"


def test_scaffold_product_web_type_writes_package_json_not_pyproject(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    written = setup.scaffold_product(target, "web")
    assert (target / "package.json") in written
    assert not (target / "pyproject.toml").exists()


def test_scaffold_product_tooling_type_writes_neither_manifest(tmp_path):
    target = tmp_path / "pinky-foo"
    target.mkdir()
    setup.scaffold_product(target, "tooling")
    assert not (target / "pyproject.toml").exists()
    assert not (target / "package.json").exists()


def test_repo_type_drives_resolve_extras_the_same_way_a_hand_built_repo_would(tmp_path):
    cases = {
        "lib": ["python"],
        "data": ["python", "snowflake"],
        "web": ["web"],
        "tooling": [],
    }
    for repo_type, expected in cases.items():
        target = tmp_path / f"pinky-{repo_type}"
        target.mkdir()
        setup.scaffold_product(target, repo_type)
        assert setup.resolve_extras(target) == expected, repo_type


def test_new_repo_scaffold_flag_writes_stubs_before_distribution(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(
        setup.precommit, "run_distribution", lambda args: calls.append(args.repo)
    )

    args = argparse.Namespace(
        repo=None,
        all=False,
        dry_run=True,
        check_drift=False,
        commit=False,
        scaffold=True,
    )
    setup.new_repo("pinky-foo", args)

    target = tmp_path / "pinky-foo"
    assert (target / "README.md").exists()
    assert (target / "docs" / "adr").is_dir()
    assert calls == ["pinky-foo"]


def test_new_repo_passes_type_through_to_scaffold(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(setup.precommit, "run_distribution", lambda args: None)

    args = argparse.Namespace(
        repo=None,
        all=False,
        dry_run=True,
        check_drift=False,
        commit=False,
        scaffold=True,
        type="web",
    )
    setup.new_repo("pinky-foo", args)

    target = tmp_path / "pinky-foo"
    assert (target / "package.json").exists()
    assert not (target / "pyproject.toml").exists()


def test_new_repo_without_scaffold_flag_skips_product_stubs(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.precommit, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(setup.precommit, "run_distribution", lambda args: None)

    args = argparse.Namespace(
        repo=None,
        all=False,
        dry_run=True,
        check_drift=False,
        commit=False,
        scaffold=False,
    )
    setup.new_repo("pinky-foo", args)

    target = tmp_path / "pinky-foo"
    assert (target / ".git").exists()
    assert not (target / "README.md").exists()
