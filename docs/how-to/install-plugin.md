# How to install a plugin at the right scope
*Update date : 2026-09-08 12:00*

```bash
pinky install --plugin <plugin-id> --marketplace <marketplace> [--yes]
```

One command. It:

1. **Fetches the plugin's files** — shells out to `claude plugin install <plugin-id>@<marketplace>
   --scope user --yes` (then `claude plugin update`, so a re-run picks up a changed plugin). There
   is no fetch-only mode, so this also enables the plugin at user scope — **transiently**: for a
   plugin that ends up project-scoped, step 2 drops that user enable once the real targets are
   placed. It stays only for a plugin you keep at user scope (a status line).

2. **Then, one of two things:**
   - **A plugin that ships a status line** (`scripts/statusline.py` in its files) → `pinky` writes
     `statusLine` and `subagentStatusLine` into `~/.claude/settings.json`, pointing at the installed
     scripts (resolved from `~/.claude/plugins/installed_plugins.json`, never a guessed path). The
     main-session `statusLine` key has no plugin-manifest slot — only `agent` and
     `subagentStatusLine` are read from a plugin's bundled `settings.json` — so `pinky` wires it
     explicitly. User scope: a status line is a cross-session preference (ADR-0001), so the step-1
     enable is correct and stays. Re-run after `claude plugin update` — the path carries the
     plugin version.
   - **Any other plugin** → an interactive wizard asks **user or project**, then (project) a depth
     (root / a group like `pinky-lib/` / a repo nested under a group) and **one or more targets**
     at that depth. Each target gets `claude plugin install --scope project` run from its own
     directory — Claude Code's own command writes `<target>/.claude/settings.json` `enabledPlugins`
     and a `{scope: project, projectPath: <target>}` registry entry (measured 2026-09-02); `pinky`
     no longer hand-merges the key. `pinky` then drops the transient user-scope enable from step 1
     — unless the plugin was already a legitimate global enable before the command ran, in which
     case it is left alone. A wizard refusal (bad answer, no tty) undoes the step-1 enable the same
     way.

3. **Rescopes — removes an enable the new targets no longer cover.** Before steps 1–2 run, `pinky`
   snapshots where this plugin is currently enabled. Once the wizard's targets are known, any
   snapshotted scope that isn't among them is removed too — a real `claude plugin uninstall
   --scope <scope>` per stale scope, so re-running `--plugin` with different targets no longer
   leaves the old ones silently enabled forever. It only fires when there is something to remove,
   and it asks first:
   ```
   Also remove <plugin-id> from: <stale-scope-1>, <stale-scope-2>? [y/N]
   ```
   `--yes` skips the prompt and confirms. In a non-interactive shell without `--yes`, nothing is
   removed — `pinky` prints what's left in place instead of guessing. A scope where the plugin is
   explicitly set to `false` (a deliberate "parent wins, off here" opt-out) is **not** touched:
   an install only ever adds a scope, it does not undo an opt-out.

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
therefore assumes the plugin is already installed; it only handles *where* it's enabled (and, as
of step 3, where it's no longer supposed to be).

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
- **Does not see a scope inside a git repo nested in another git repo.** The scope scan
  (`plugin_scope._collect`) prunes at the first `.git` it meets and never descends into a repo, so
  a `.claude/settings.json` in a repo-within-a-repo is invisible to both the rescope snapshot and
  `pinky plugins reconcile`, and stays untouched however you rescope. Group nesting itself is
  unbounded — a group many levels down still counts.
- **Does not know when a scope is required by another plugin's declared dependency.** Step 3 only
  ever purges the plugin you're installing — rescoping `pc-craft` never touches `pc-privacy`'s
  scopes even when `pc-craft` declares `pc-privacy` in its `.claude-plugin/plugin.json`
  `dependencies`. `pinky plugins reconcile` surfaces that as `required by: pc-craft` on the
  dependency's block; this command does not warn you before you remove such a scope yourself.
