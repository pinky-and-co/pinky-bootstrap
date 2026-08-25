# AGENTS.md — pinky-bootstrap

CLI that distributes non-agentic hygiene tooling (ruff, pre-commit, CI templates) into the
pinky-and-co plugin org's repos — the `.claude-plugin/` structures themselves (skills, hooks) are
authored by hand in each plugin repo, not generated here.

Content here is neutral and tool-agnostic — readable by any agentic tool (Claude Code, Codex,
Cursor…), no tool-specific mechanics (no slash-command name, no literal model id).

## Scope boundary — this CLI starts where the plugin mechanism stops

**The criterion, not the list: an artefact belongs here only while no native plugin slot can carry
it.** Everything a plugin can declare is authored and distributed as a plugin; this repo covers what
the plugin manifest has no field for, plus what is not agentic at all (hygiene hooks, CI templates).

The boundary is **dated, not permanent** — the manifest gains fields, and each one it gains removes
a reason for this CLI to exist. When a slot appears upstream, the artefact migrates out of here; it
never stays for continuity's sake. Two consequences that are easy to get backwards:

- Never conclude an artefact belongs here from a past measurement. Re-measure the manifest against
  the installed version before deciding — `plugin.json` gained `dependencies` (array of `plugin` or
  `plugin@marketplace` strings, resolved at install) on 2026-08-22, after this repo had already been
  justified in part by its absence.
- Never widen the boundary to what a plugin *could* carry but does not carry *yet* in our repos.
  That is a migration to schedule, not a missing slot.

Covered here as of 2026-08-25, each for the same reason — customisation presets with no plugin
slot: output styles, themes, rules.

## Branch strategy

GitHub Flow — the resolved value the skills rely on lives in `.claude/policies.json`, this is
orientation only.

## Repo conventions

- `test_validate_frontmatter.py` defines the contract for `scripts/hooks/validate_frontmatter.py`
  — a validator for SKILL.md / agent frontmatter that also rejects legacy `commands/` directories
  in plugin repos. Write the hook to satisfy the existing tests, not the reverse.
