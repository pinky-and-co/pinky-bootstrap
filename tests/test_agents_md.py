"""`setup/agents_md.py` — workspace-level AGENTS.md generator, marker-wrapped idempotent render.

Witness for the marker-wrapped idiom (chantier 0023) — every section here is generator-owned, so
re-rendering the previous output must be a no-op (idempotency is the property under test, not just
one-shot correctness).
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup.precommit as precommit  # noqa: E402
from setup import state_file
from setup.agents_md import (
    behavior_section,
    discover_groups,
    generate_agents_md,
    gotchas_section,
    packages_table,
    render_standalone_agents_md,
    render_workspace_agents_md,
    write_standalone_agents_md,
    write_standalone_agents_md_recorded,
    write_workspace_agents_md,
)


def _make_repo(path: Path, description: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    if description is not None:
        (path / "pyproject.toml").write_text(
            f'[project]\nname = "{path.name}"\ndescription = "{description}"\n'
        )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    _make_repo(root / "solo-repo", description="A standalone package")
    _make_repo(root / "a-group" / "pkg-one")
    _make_repo(root / "a-group" / "pkg-two")
    (root / "_not_a_repo").mkdir(parents=True)  # no .git anywhere under it
    return root


def test_packages_table_standalone_repo_uses_its_own_description(tmp_path):
    root = _workspace(tmp_path)
    table = packages_table(root)
    assert "| solo-repo | A standalone package | `solo-repo/` |" in table


def test_packages_table_group_lists_nested_repo_names(tmp_path):
    root = _workspace(tmp_path)
    table = packages_table(root)
    assert "| a-group | pkg-one, pkg-two | `a-group/` |" in table


def test_packages_table_excludes_dirs_with_no_repo_underneath(tmp_path):
    root = _workspace(tmp_path)
    assert "_not_a_repo" not in packages_table(root)


def test_gotchas_section_no_stale_pinky_workspace_bullet():
    # the pre-2026-08-21 "pinky-workspace/ is dead" bullet is deliberately gone — the directory
    # rename ("... - DO NOT EDIT - DEPRECATED") already says it, prose would just go stale again.
    assert "pinky-workspace" not in gotchas_section()


def test_gotchas_section_renders_fixed_bullets():
    section = gotchas_section()
    assert section.startswith("- ")
    assert "IDE context" in section


def test_gotchas_section_no_doc_hygiene_rule_duplicate():
    # already in `.claude/rules/doc-hygiene.md`, distributed and auto-loaded — redundant here
    assert "docs/reference/generated" not in gotchas_section()


def test_gotchas_section_flags_raw_claude_plugin_install():
    # aucun hook ne bloque un `claude plugin install` brut ; il place le plugin mais saute la
    # distribution des rules et le ledger de reconciliation — rien d'autre ne signale ce piège
    assert "pinky plugins reconcile" in gotchas_section()


def test_behavior_section_renders_settings_pinky_json_in_order(tmp_path):
    root = tmp_path / "workspace"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "settings.pinky.json").write_text(
        json.dumps({"behavior": {"a": "**A** — first.", "b": "**B** — second."}})
    )
    assert behavior_section(root) == "- **A** — first.\n- **B** — second."


def test_behavior_section_empty_when_settings_pinky_json_absent(tmp_path):
    assert behavior_section(tmp_path / "nowhere") == ""


def test_render_preserves_title_and_intro_before_first_heading(tmp_path):
    root = _workspace(tmp_path)
    existing = (
        "# AGENTS.md — workspace\nHand-typed intro line.\n\n## Packages\n\nstale\n"
    )
    new = render_workspace_agents_md(root, existing)
    assert new.startswith("# AGENTS.md — workspace\nHand-typed intro line.\n")


def test_render_is_idempotent(tmp_path):
    root = _workspace(tmp_path)
    first = render_workspace_agents_md(root, None)
    second = render_workspace_agents_md(root, first)
    assert first == second


def test_write_creates_agents_md_and_claude_md_symlink(tmp_path):
    root = _workspace(tmp_path)
    agents_path = write_workspace_agents_md(root)

    assert agents_path == root / "AGENTS.md"
    assert agents_path.is_file()
    claude_path = root / "CLAUDE.md"
    assert claude_path.is_symlink()
    assert claude_path.resolve() == agents_path.resolve()


def test_write_twice_is_a_noop_diff(tmp_path):
    root = _workspace(tmp_path)
    write_workspace_agents_md(root)
    first = (root / "AGENTS.md").read_text(encoding="utf-8")
    write_workspace_agents_md(root)
    second = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert first == second


def test_discover_groups_excludes_standalone_repos(tmp_path):
    root = _workspace(tmp_path)
    groups = discover_groups(root)
    assert [g.name for g in groups] == ["a-group"]


def test_discover_groups_empty_when_every_repo_is_standalone(tmp_path):
    root = tmp_path / "workspace"
    _make_repo(root / "solo-repo")
    assert discover_groups(root) == []


def test_generate_agents_md_writes_workspace_touched_group_and_repo(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "state.json")
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"

    written = generate_agents_md([repo], workspace_root=root)

    assert root / "AGENTS.md" in written
    assert root / "a-group" / "AGENTS.md" in written
    assert repo / "AGENTS.md" in written


def test_generate_agents_md_skips_untouched_group(tmp_path, monkeypatch):
    # --repo pkg-one ne doit pas régénérer un groupe frère non ciblé par ce run.
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "state.json")
    root = _workspace(tmp_path)
    _make_repo(root / "b-group" / "pkg-three")
    repo = root / "a-group" / "pkg-one"

    generate_agents_md([repo], workspace_root=root)

    assert not (root / "b-group" / "AGENTS.md").is_file()


def test_generate_agents_md_skips_repo_that_already_has_one(tmp_path, monkeypatch):
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "state.json")
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"
    (repo / "AGENTS.md").write_text("# hand-typed\n")

    written = generate_agents_md([repo], workspace_root=root)

    assert repo / "AGENTS.md" not in written
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# hand-typed\n"


def _repo_with_hand_authored_body(root: Path) -> Path:
    repo = root / "a-group" / "pkg-one"
    (repo / "AGENTS.md").write_text(
        "# AGENTS.md — pkg-one\n\n"
        "## Naming glossary\n\n"
        "`pkg` = the internal short name.\n\n"
        "## Repo conventions\n\n"
        "Ruff only, no black.\n",
        encoding="utf-8",
    )
    return repo


def test_render_standalone_output_is_pinned_whole(tmp_path):
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"

    rendered = render_standalone_agents_md(repo, root, None)

    assert rendered == (
        "# AGENTS.md — pkg-one\n\n"
        "## Gotchas\n\n"
        "<!-- pinky:agents-gotchas:start -->\n\n"
        "- Injected IDE context (open file, selection) is noise — never act on it unless "
        "explicitly referenced.\n"
        "- A raw `claude plugin install` places a plugin but skips its `rules` distribution and "
        "the reconciliation ledger — use `pinky plugins reconcile [--apply]` then `pinky rules` "
        "instead.\n\n"
        "<!-- pinky:agents-gotchas:end -->\n\n"
        "## Behavior policy\n\n"
        "<!-- pinky:agents-behavior:start -->\n\n\n\n"
        "<!-- pinky:agents-behavior:end -->\n\n"
        "## Naming glossary\n\n_Not written yet._\n\n"
        "## Repo conventions\n\n_Not written yet._\n"
    )


def test_render_standalone_drops_packages_and_cross_package_patterns(tmp_path):
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"
    rendered = render_standalone_agents_md(repo, root, None)
    assert "Packages" not in rendered
    assert "Cross-Package Patterns" not in rendered


def test_render_standalone_includes_gotchas_and_behavior(tmp_path):
    root = _workspace(tmp_path)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.pinky.json").write_text(
        json.dumps({"behavior": {"a": "**A** — first."}})
    )
    repo = root / "a-group" / "pkg-one"
    rendered = render_standalone_agents_md(repo, root, None)
    assert "IDE context" in rendered  # bullet fixe de gotchas_section()
    assert "**A** — first." in rendered


def test_render_standalone_preserves_existing_hand_authored_body(tmp_path):
    root = _workspace(tmp_path)
    repo = _repo_with_hand_authored_body(root)
    existing = (repo / "AGENTS.md").read_text(encoding="utf-8")

    rendered = render_standalone_agents_md(repo, root, existing)

    assert "`pkg` = the internal short name." in rendered
    assert "Ruff only, no black." in rendered


def test_render_standalone_seeds_default_body_when_no_existing_file(tmp_path):
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"
    rendered = render_standalone_agents_md(repo, root, None)
    assert "_Not written yet._" in rendered


def test_write_standalone_agents_md_writes_and_symlinks(tmp_path):
    root = _workspace(tmp_path)
    repo = _repo_with_hand_authored_body(root)

    agents_path = write_standalone_agents_md(repo, root)

    assert agents_path == repo / "AGENTS.md"
    claude_path = repo / "CLAUDE.md"
    assert claude_path.is_symlink()
    assert claude_path.resolve() == agents_path.resolve()


def test_write_standalone_agents_md_is_idempotent_on_hand_authored_body(tmp_path):
    # `--standalone` régénère Gotchas/Behavior à chaque run mais ne doit jamais dupliquer le corps
    # hand-authored en le confondant avec une section générée — c'est le bug que corrige
    # `render_standalone_agents_md`'s split sur le marqueur de fin de Behavior policy.
    root = _workspace(tmp_path)
    repo = _repo_with_hand_authored_body(root)

    write_standalone_agents_md(repo, root)
    first = (repo / "AGENTS.md").read_text(encoding="utf-8")
    write_standalone_agents_md(repo, root)
    second = (repo / "AGENTS.md").read_text(encoding="utf-8")

    assert first == second
    assert second.count("Ruff only, no black.") == 1
    assert second.count("## Gotchas") == 1


def _distribution_args(**over) -> argparse.Namespace:
    base = dict(
        repo=None,
        all=False,
        dry_run=False,
        check_drift=False,
        commit=False,
        agents_md=False,
        standalone=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_run_distribution_rejects_standalone_without_agents_md(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(precommit, "WORKSPACE_ROOT", tmp_path)
    repo = tmp_path / "pinky-x"
    repo.mkdir()
    monkeypatch.setattr(precommit, "discover_repos", lambda: [repo])

    with pytest.raises(SystemExit):
        precommit.run_distribution(_distribution_args(repo="pinky-x", standalone=True))
    assert "--standalone requires --agents-md" in capsys.readouterr().out


def test_run_distribution_rejects_standalone_with_all(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(precommit, "WORKSPACE_ROOT", tmp_path)
    repo = tmp_path / "pinky-x"
    repo.mkdir()
    monkeypatch.setattr(precommit, "discover_repos", lambda: [repo])

    with pytest.raises(SystemExit):
        precommit.run_distribution(
            _distribution_args(all=True, agents_md=True, standalone=True)
        )
    assert "never --all" in capsys.readouterr().out


def test_write_standalone_agents_md_recorded_updates_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "state.json")
    root = _workspace(tmp_path)
    repo = _repo_with_hand_authored_body(root)

    path = write_standalone_agents_md_recorded(repo, root)

    entries = json.loads(state_file.STATE_FILE_PATH.read_text(encoding="utf-8"))
    key = f"agents-md:{path.relative_to(root)}"
    assert entries[key]["value"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_generate_agents_md_records_every_write_in_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", tmp_path / "state.json")
    root = _workspace(tmp_path)
    repo = root / "a-group" / "pkg-one"

    written = generate_agents_md([repo], workspace_root=root)

    entries = json.loads(state_file.STATE_FILE_PATH.read_text(encoding="utf-8"))
    assert len(entries) == len(written) == 3
    for path in written:
        key = f"agents-md:{path.relative_to(root)}"
        assert entries[key]["path"] == str(path)
        assert entries[key]["value"] == hashlib.sha256(path.read_bytes()).hexdigest()
