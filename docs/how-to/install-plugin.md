# How to install a plugin at the right scope
*Update date : 2026-08-28 13:18*

```bash
pinky install --plugin <plugin-id> --marketplace <marketplace>
```

One command. It:

1. **Fetches the plugin's files** — shells out to `claude plugin install <plugin-id>@<marketplace>
   --scope user --yes` (then `claude plugin update`, so a re-run picks up a changed plugin). This
   also enables the plugin at user scope.

2. **Then, one of two things:**
   - **A plugin that ships a status line** (`scripts/statusline.py` in its files) → `pinky` writes
     `statusLine` and `subagentStatusLine` into `~/.claude/settings.json`, pointing at the installed
     scripts (resolved from `~/.claude/plugins/installed_plugins.json`, never a guessed path). The
     main-session `statusLine` key has no plugin-manifest slot — only `agent` and
     `subagentStatusLine` are read from a plugin's bundled `settings.json` — so `pinky` wires it
     explicitly. User scope: a status line is a cross-session preference (ADR-0001). Re-run after
     `claude plugin update` — the path carries the plugin version.
   - **Any other plugin** → an interactive wizard places `enabledPlugins["<id>@<marketplace>"] =
     true` at a chosen workspace depth (root / a group like `pinky-lib/` / a repo nested under a
     group), because Claude Code's own `--scope` only knows user/project/local, not this
     workspace's hierarchy. Merged into `<target>/.claude/settings.json`, that one key only.

     > **Known overlap** (chantier 0023, à reconcilier) : step 1's `--scope user` already enables
     > the plugin at user level, so the wizard's narrower placement is additive, not exclusive. The
     > wizard needs a rework to fetch-without-enabling for the depth case.

## During plugin development — local marketplace instead of GitHub

`github` is not the only marketplace source type. While actively iterating on a plugin repo,
register it as a **`directory`-source marketplace** pointing at your local clone instead
(ADR-0002):

```bash
claude plugin marketplace add /absolute/path/to/bootstrap/<plugin-repo>
```

Then `claude plugin install <local-marketplace-name>@<plugin-id>` as usual (step 1 above), and the
scope wizard (step 2) doesn't change. Rebasculer sur `github` avant de livrer pour de vrai —
`directory` est une commodité par machine, jamais commitée.

### Why `directory` skips the reload for a hook edit — and what still needs one

Verified 2026-08-21 against `~/.claude/plugins/known_marketplaces.json`: a `directory`-source entry
records `installLocation` **equal to** `source.path` — no copy is ever made. A `github` (or `url`/
`npm`) source instead gets fetched into `~/.claude/plugins/cache/<marketplace>/` and
`~/.claude/plugins/marketplaces/<marketplace>/`, a real local snapshot, separate from wherever the
upstream repo lives. `${CLAUDE_PLUGIN_ROOT}` resolves to `installLocation` either way — so under
`directory`, it IS your working tree; under `github`, it's a cache copy that only a fetch/update
step refreshes.

A hook's **command** (`hooks.json` → `python3 "${CLAUDE_PLUGIN_ROOT}/.../guard.py"`) is a path,
re-executed as a fresh subprocess on every matching tool call — nothing about the script's body is
cached in-process. So under `directory`, editing a hook script's logic takes effect on the very
**next tool call**, no `/reload-plugins --force` needed at all — proven live during the guard.py
`GENERATED_TREES` fix (chantier 0023, 2026-08-21): the fix landed and the next `Edit` call already
honored it.

**Not the same guarantee for everything a plugin declares.** This only covers a script's own body,
executed fresh each call. Structural changes — a new/renamed skill file, a new `hooks.json` entry,
`plugin.json` itself — are plugin metadata Claude Code most likely loads once when the session/
plugin initializes; **not verified today which of these need `/reload-plugins --force` (or a fresh
session) vs pick up live**. Until checked case by case, keep reloading for anything beyond editing
an existing hook/skill script's own logic.

Separately: `.claude/rules/`, `.claude/settings.pinky.json` and anything else `pinky distribute`/`pinky
rules` renders into a *consuming* repo are a **copy**, made by that CLI step — unrelated to
marketplace source type. Editing the plugin's source never updates that copy; only rerunning the
CLI distribution command does, `directory`-source or not.

## Why two steps, not one

`enabledPlugins` does **not** trigger an automatic download — a plugin listed there has no effect
until it's already installed locally (`claude plugin install` first). `pinky install --plugin`
therefore assumes the plugin is already installed; it only handles *where* it's enabled.

## Where a plugin can be scoped, concretely

`.claude/settings.json` resolves per git-repo-root (ADR-0001) — a group directory (`pinky-lib/`,
`bootstrap/`, ...) is not itself a git repo, but a `.claude/settings.json` posed there still
applies to sessions started in any repo nested under it. Three real targets, one mechanism:

| Depth | Example target | Reaches |
|---|---|---|
| 0 | workspace root | every repo in the workspace |
| 1 | `pinky-lib/` (a group) | every repo nested under `pinky-lib/` |
| 1 | `bootstrap/pinky-bootstrap` (a repo directly at depth 1) | that repo only |
| 2 | `pinky-lib/pinky-core` | that repo only |

## What this does not do

- **Does not re-decide `enabledPlugins` scope for a status-line plugin** — those go to user scope
  unconditionally (a cross-session preference), no depth wizard.
- **Does not refresh a stale `statusLine` path on its own after `claude plugin update`** — the
  written path carries the plugin version, so re-run `pinky install --plugin <id>` to re-resolve it
  (it reads the live path from `installed_plugins.json` every run).
