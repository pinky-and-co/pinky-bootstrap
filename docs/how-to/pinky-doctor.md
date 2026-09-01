# How to check what installed plugins need — `pinky doctor`
*Update date : 2026-09-01 17:37*

```bash
pinky doctor
```

Reports the prerequisites the plugins on this machine assume but no manifest declares, then exits
non-zero if any is missing. Read-only — it writes no config and no `pinky install` ledger entry.

## What it checks

1. **External binaries.** For every installed plugin (`~/.claude/plugins/installed_plugins.json`,
   all scopes), `pinky` reads the `Bash(...)` entries of its skills' and agents' `allowed-tools`
   frontmatter — `Bash(rg:*)`, `Bash(command -v prek:*)`, `Bash(gh run list:*)` — and resolves the
   binary name out of each. Path commands (`Bash(${CLAUDE_PLUGIN_ROOT}/…)`) and `mcp__…` entries
   contribute nothing. Binaries every machine already has (`git`, `find`, `python3`, `curl`, …) are
   subtracted, so the report lists only what you might actually need to install. Each remaining
   binary is checked with `shutil.which()` and attributed to the plugins that need it.

2. **Local Ollama.** If `model_pool` in `~/.claude/settings.pinky.json` has a `kind: offline`
   entry, `pinky` checks the endpoint (`PINKY_OLLAMA_URL`, default `http://localhost:11434`) is
   reachable and the default model (`gemma4:12b`) is listed by its `/api/tags` API.

3. **API keys.** For every entry in the `keys` section of `settings.pinky.json`, `pinky` checks the
   `env` var resolves — either it is set in the environment, or `security find-generic-password -s
   <service>` finds it in the macOS keychain.

## Fixing what is missing

```bash
pinky doctor --fix
```

Prompts (`y`/`N`) to `brew install` each missing binary, and `brew install ollama` if the Ollama
endpoint is down. It never runs `ollama pull` and never touches API keys — those print an
actionable line and nothing more. When `brew` is not on the PATH it prints the manual steps and
runs nothing.

`_BREW_FORMULA` in `setup/doctor.py` maps a binary to its formula only where the two differ
(`rg` → `ripgrep`); everything else is tried as `brew install <name>`. A binary with no such
formula (`markitdown`, `prek` — installed another way) fails visibly there, which is the signal to
install it yourself.

## Inside `pinky install`

Every `pinky install` path runs `pinky doctor` at the end — `--plugin` included, since that is the
path that activates a plugin whose prerequisites are new. There it is **advisory**: the report
prints, but a missing prerequisite never fails the install and never undoes an activated plugin.

## Exit code

`pinky doctor` (not `--fix`) exits `1` when any MUST prerequisite is missing, `0` otherwise — so it
can gate a CI step or a machine-provisioning script. The advisory call inside `pinky install` does
not propagate that code.

## What this does not do

- **Does not detect a binary a skill only uses in its body.** The scan sees `allowed-tools`
  frontmatter only — a skill that shells `uv` without declaring `Bash(uv:*)` is missed. The check
  is advisory precisely because it can under-report.
- **Does not check non-pinky MCP servers** (`context7`) — there is no way to verify one responds
  without launching it.
- **Does not remember to re-run itself** after `claude plugin update` — the installed plugin set
  changes, so re-run `pinky doctor` when it does.
- **macOS only** — `--fix` uses `brew`, key resolution uses `security`.
