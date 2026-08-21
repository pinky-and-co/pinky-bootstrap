"""`setup/agents_md.py` — workspace-level AGENTS.md generator, marker-wrapped idempotent render.

Witness for the marker-wrapped idiom (chantier 0023) — every section here is generator-owned, so
re-rendering the previous output must be a no-op (idempotency is the property under test, not just
one-shot correctness).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.agents_md import (
    behavior_section,
    gotchas_section,
    packages_table,
    render_workspace_agents_md,
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


def test_behavior_section_renders_policies_json_in_order(tmp_path):
    root = tmp_path / "workspace"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "policies.json").write_text(
        json.dumps({"behavior": {"a": "**A** — first.", "b": "**B** — second."}})
    )
    assert behavior_section(root) == "- **A** — first.\n- **B** — second."


def test_behavior_section_empty_when_policies_json_absent(tmp_path):
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
