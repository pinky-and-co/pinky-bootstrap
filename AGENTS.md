# AGENTS.md — pinky-bootstrap

CLI that distributes non-agentic hygiene tooling (ruff, pre-commit, CI templates) into the
pinky-and-co plugin org's repos — the `.claude-plugin/` structures themselves (skills, hooks) are
authored by hand in each plugin repo, not generated here.

Content here is neutral and tool-agnostic — readable by any agentic tool (Claude Code, Codex,
Cursor…), no tool-specific mechanics (no slash-command name, no literal model id).

## Branch strategy

GitHub Flow — the resolved value the skills rely on lives in `.claude/policies.json`, this is
orientation only.

## Repo conventions

- `test_validate_frontmatter.py` defines the contract for `scripts/hooks/validate_frontmatter.py`
  — a validator for SKILL.md / agent frontmatter that also rejects legacy `commands/` directories
  in plugin repos. Write the hook to satisfy the existing tests, not the reverse.
