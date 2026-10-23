---
title: Layout of `~/.claude/`
---
# Layout of `~/.claude/` — who writes what, and where
*Update date : 2026-10-23 17:41*

Every file or directory the `pinky` CLI and the plugins create under `~/.claude/` has a single
owner. The uninstall rule follows from it: once every plugin is uninstalled and `~/.claude/pinky/`
is removed, no entry named `pinky*` or `pc-*` remains besides `settings.pinky.json` — except a
legacy `pinky-*` file that migration left in place, either because its `pinky/` form already
existed (both stay untouched) or because the move failed (the next CLI start retries). Keys the CLI
wrote inside Claude Code's own `settings.json` are not entries of that kind; they are tracked in the
ledger below.

## `pinky` CLI — `~/.claude/pinky/`

Everything the `pinky` CLI owns lives in this directory: one removal, and a future file cannot be
forgotten on a list.

| Path | Role |
|---|---|
| `~/.claude/pinky/install-state.json` | Ledger of what `pinky` laid down — the `statusLine` / `subagentStatusLine` and an environment variable in `settings.json`, and the plugin enables it wrote into settings files (project `.claude/settings.json` files included, outside `~/.claude/`). Used for removal: losing it makes `pinky` forget what it owns. |
| `~/.claude/pinky/curated-plugins.toml` | Curated plugin list, layered over the list embedded in the repo. |
| `~/.claude/pinky/plugin-scope/` | Plugin scope state shared between the CLI and the plugins: written by the plugins' hooks and vendored scripts (`plugin_scope_lib.py` / `pending_user_action.py` copies); the CLI only deletes the legacy copy at migration. It lives on the CLI side rather than in a single plugin's data, because it belongs to no plugin alone — and because scripts launched by the Bash tool do not receive `${CLAUDE_PLUGIN_DATA}`. |

## Plugins — `~/.claude/pinky/plugin-state/<plugin>/`

State whose location a mod chooses, or that a mod's child writes. A mod and its children never
receive `${CLAUDE_PLUGIN_DATA}` (measured 2026-10-23: `$.env.get` unset in the mod, `printenv`
empty in a `$.process.run` child): this is therefore the location for such state. Removed together
with `~/.claude/pinky/`.

| Path | Role |
|---|---|
| `~/.claude/pinky/plugin-state/pc-core/` | `pc-core` plugin: the `subagent-routing.jsonl` routing journal, written by the `subagent-routing` mod's child (`journal.py`). The first write also deletes the legacy `~/.claude/pc-core/`. |
| `~/.claude/pinky/plugin-state/pc-models/pi-runs/` | `pc-models` plugin: live call directories (`pi-runs/`), named by the `pi-view` mod, created and written by the MCP server. The first access also deletes the legacy `pc-models/` directory. |

Known limit: `pi_live.py` and the `pi-view` mod resolve the base directory from
`CLAUDE_CONFIG_DIR` first, while the CLI paths above are fixed at `~/.claude/` — with that variable
set, the two write to different places. Left as is on purpose (path resolution is outside the
uninstall work) and tracked as an open point.

## Plugins — `${CLAUDE_PLUGIN_DATA}` = `~/.claude/plugins/data/<plugin>-<marketplace>/`

Default rule for plugin hooks and stdio MCP servers: it is the only plugin location that
`claude plugin uninstall` cleans up — any other name under `plugins/data/` survives the
uninstall. Not visible to mods (see above).

## Claude Code's — do not move

| Path | Role |
|---|---|
| `~/.claude/rules/` | Claude Code's native directory for user rules. |
| `~/.claude/settings.json` | Claude Code configuration. The CLI edits a few keys in it (`statusLine`, `subagentStatusLine`, an `env` entry, plugin enables) and records each in the ledger so it can be reverted. |
| `~/.claude/plugins/` | Installed plugins and their data, managed by Claude Code. |
| `~/.claude/projects/` | Session history, per project. |
| `~/.claude/output-styles/` | Output styles. |

## Hand-written

| Path | Role |
|---|---|
| `~/.claude/settings.pinky.json` | Configuration specific to each consuming repo, written by hand — its name mirrors the project-level one (`.claude/settings.pinky.json`). |
