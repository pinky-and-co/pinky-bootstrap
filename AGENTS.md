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
slot: rules.

## Branch strategy

GitHub Flow — the resolved value the skills rely on lives in `.claude/settings.pinky.json`, this is
orientation only.

## Repo conventions

- `test_validate_frontmatter.py` defines the contract for `scripts/hooks/validate_frontmatter.py`
  — a validator for SKILL.md / agent frontmatter that also rejects legacy `commands/` directories
  in plugin repos. Write the hook to satisfy the existing tests, not the reverse.
- Who installed a plugin, or wrote an enable: `pinky claude-plugin list --who` matches each `installed_plugins.json`
  entry to the session transcript (`~/.claude/projects/`) that ran `claude plugin install` at that
  time; an entry no command matches came from a hook or a script (`pc-autodiscovery`, `chantier`,
  `spawn-workers`). Run it before diagnosing an unexpected enable, and read `_AGENT_LOG` first.
- Every consumer repo's `pyproject.toml` carries `[tool.uv] exclude-newer = "3 days"` — a relative
  cooldown span (uv ≥ 0.9.17) against a freshly compromised dependency republished on PyPI: uv
  ignores, at every `uv lock`, any package published in the last 3 days, and records the span
  itself (not a resolved date) as `exclude-newer-span` in `uv.lock`. Alongside it,
  `required-version = ">=0.9.17"` so an older uv fails loudly instead of silently ignoring the
  span. Both are the only keys `distribute()` writes into a file it otherwise only reads
  (`render_pyproject_with_cooldown` in `setup/precommit.py`). In steady state it writes them once
  and never again, so a `pinky repo distribute` run passing through for any other reason leaves
  `pyproject.toml` untouched and cannot desync `uv.lock`. The **one** run that does rewrite it is
  the migration off the old absolute-date form: on that run `pyproject.toml` moves to the span
  while `uv.lock` still holds the old timestamp, so each repo needs a one-time `uv lock` (then a
  PR) before its `uv sync --locked` CI is green again. After that the span slides on its own —
  nothing to renew, no scheduled job. The only moment the cooldown then bites is a deliberate
  `uv lock` (adding or bumping a dependency); review the resolution diff in that PR, since nothing
  else bounds it.
