# How to install a plugin at the right scope
*Update date : 2026-09-23 11:04*

```bash
pinky claude-plugin install [<plugin-id> ...] [--marketplace <marketplace>] [--scope <path>] [--workspace <path>] [--yes] [--dry-run] [--force]
```

`install <plugin-id>` downloads the plugin then runs it straight through the same plugin × target
table as `pinky claude-plugin enable` (FR-0024-31) — a plugin already enabled somewhere shows those
targets pre-checked, and the plan is the same one `enable` prints. Several plugin ids in one call
share a single table and a single confirmation.

**No plugin id at all** opens a checkbox list instead — every plugin the curated list names
(`setup/data/curated_plugins.toml`, a `~/.claude/pinky-curated-plugins.toml` user file layered on
top, or `--list <path>`) plus every plugin already installed, the installed ones pre-checked. With
nothing installed yet, the whole curated list starts checked (a fresh machine bootstraps with all
of it by default). A whole-marketplace curated entry expands to the individual plugins it
publishes by reading that marketplace's own catalog — but only when this machine already has it
registered (`claude plugin marketplace add`, once, by hand or via an earlier `install`/`enable`
run). **A marketplace this machine has never registered contributes no rows at all** — a genuinely
fresh machine needs `claude plugin marketplace add <source>` run once per curated marketplace
before its plugins show up in this list; naming a plugin directly (`install pc-x --marketplace
<name>`) always works regardless. `pinky claude-plugin enable` (no name) opens the same list;
`pinky claude-plugin disable` (no name) skips the list and acts on every currently installed
plugin directly — nothing to curate when the point is removal.

1. **`Workspace: <path> (via <origin>)`** is always the first line — `--workspace` takes priority
   over `PINKY_WORKSPACE_ROOT`, which takes priority over the nearest `*.code-workspace` marker
   above the current directory.

2. **The table**, one row per known target (`user` first, then the workspace root, then every
   group/repo below it), checkbox-prefilled from where the plugin is *already* enabled
   (`installed_plugins.json` + every `settings.json`). Toggle indices to flip a row, Enter to keep
   it as shown — checking `user` enables it there, unchecking a previously-checked row removes that
   enable. `--scope <path>` (repeatable, workspace-relative or `user`) replaces the table entirely
   and answers no question. Nothing is downloaded or written before the plan below is confirmed.

3. **The plan, then `[y/N]`.** Added/removed/unchanged targets, plus the rules that follow the
   plugin to the same scopes (FR-0024-52). `--yes` skips the confirmation; `--dry-run` prints the
   plan and writes nothing. Applying it runs `claude plugin install <plugin-id>@<marketplace>
   --scope project --yes` from each newly-checked target (Claude Code's own command, which writes
   `<target>/.claude/settings.json` and the registry entry together) or `--scope user` for a
   newly-checked `user` row — nothing is fetched at user scope on a project-only run (measured
   2026-09-02 and 2026-09-19). A row explicitly set to `false` (a deliberate "parent wins, off
   here" opt-out) never shows up as something to re-check on its own; the table only ever reflects
   what you toggle.

   **A plugin that ships a status line** (`scripts/statusline.py`) gets `statusLine` and
   `subagentStatusLine` written into `~/.claude/settings.json`, pointing at the installed scripts
   (resolved from `installed_plugins.json`, never a guessed path) — whenever the plugin is
   confirmed on disk exactly where it should be, whether this run applied a change or the table
   showed nothing left to do. `--dry-run` and a declined plan never confirm anything, so neither
   writes it. Re-run after `claude plugin update` — the path carries the plugin version.

   `--force`: delete the plugin's cache directory (`~/.claude/plugins/cache/<marketplace>/<plugin>/
   <version>/`) before the fetch, ahead of the table. `claude plugin install`/`update` only ever
   *fills* an absent cache dir, so a plugin pinned at `0.1.0` (no version bump until an actual
   release) keeps serving the stale build after you edit its working tree — `--force` is the
   automated form of the `rm -rf` you'd otherwise do by hand. No-op on a first install. The delete
   only happens when the resolved path is under `~/.claude/plugins/cache/`; a registry entry
   pointing elsewhere is refused, not removed.

A `Ctrl-C` at any prompt exits with a one-line message and code `130`, never a Python traceback
(NFR-0024-37) — nothing is written before the plan is confirmed, so an interrupt before that point
leaves nothing behind. The one gap: interrupting the *apply* loop itself after picking several
targets can leave the earlier ones already enabled and the later ones not (no rollback across
targets — accepted, see the chantier 0024 story's Open questions).

## During plugin development — local marketplace instead of GitHub

`github` is not the only marketplace source type. While actively iterating on a plugin repo,
register it as a **`directory`-source marketplace** pointing at your local clone instead
(ADR-0002):

```bash
claude plugin marketplace add /absolute/path/to/bootstrap/<plugin-repo>
```

Then `pinky claude-plugin install <plugin-id> --marketplace <local-marketplace-name>` as usual, and
the table (step 2 above) doesn't change. Rebasculer sur `github` avant de livrer pour de vrai —
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

Separately: `.claude/rules/`, `.claude/settings.pinky.json` and anything else `pinky repo distribute`/`pinky
rules` renders into a *consuming* repo are a **copy**, made by that CLI step — unrelated to
marketplace source type. Editing the plugin's source never updates that copy; only rerunning the
CLI distribution command does, `directory`-source or not.

## Why two steps, not one

`enabledPlugins` does **not** trigger an automatic download — a plugin listed there has no effect
until it's already installed locally (`claude plugin install` first). `pinky claude-plugin install`
downloads and places it in the same run, through the table: checking a row adds a scope,
unchecking a previously-checked one removes it.

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
  unconditionally (a cross-session preference), no table shown.
- **Does not refresh a stale `statusLine` path on its own after `claude plugin update`** — the
  written path carries the plugin version, so re-run `pinky claude-plugin install <id>` to re-resolve it
  (it reads the live path from `installed_plugins.json` every run).
- **Does not see a scope inside a git repo nested in another git repo.** The scope scan
  (`plugin_scope._collect`, feeding the table's rows) prunes at the first `.git` it meets and never
  descends into a repo, so a `.claude/settings.json` in a repo-within-a-repo is invisible to both
  the table and `pinky claude-plugin list`, and stays untouched however you toggle it. Group
  nesting itself is unbounded — a group many levels down still counts.
- **Does not know when a scope is required by another plugin's declared dependency.** Unchecking a
  row only ever removes the plugin you're installing — rescoping `pc-craft` never touches
  `pc-privacy`'s scopes even when `pc-craft` declares `pc-privacy` in its
  `.claude-plugin/plugin.json` `dependencies`. `pinky claude-plugin list` surfaces that as
  `required by: pc-craft` on the dependency's block; this command does not warn you before you
  remove such a scope yourself.
