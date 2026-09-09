---
title: Vendor a shared lib
---
# How to vendor a shared lib into the plugin repos

*Update date : 2026-09-09 04:18*

A small utility that **two plugins each need** cannot be imported across the plugin boundary at
runtime (`dependencies` orders install, it builds no `sys.path`). The fix is a *vendored* copy: one
source of truth here, byte-identical copies distributed into each plugin, a checksum manifest that
catches a hand-edited copy before the next distribution silently overwrites it.

Worked example: `policy_lib`, `secret_patterns`, `plugin_scope_lib`, `pending_user_action`.

## 1. Create the source of truth

```
hygiene/vendor/<name>.py
```

Plain module, no `<name> — …` prefix in the docstring (every copy carries it verbatim, and a
consumer copy's filename differs — see step 2).

## 2. Add it to `VENDOR_MAP`

`setup/precommit.py`, `VENDOR_MAP` — one entry, key = the source basename, value = every
destination path:

```python
"<name>.py": [
    "plugins/pc-core/hooks/<name>.py",                       # home module: bare name
    "plugins/pc-git/hooks/pc_git_<name>.py",                 # every consumer: pc_<plugin>_<name>.py
],
```

**The consumer copy MUST be `pc_<plugin>_<name>.py`, not the bare name.** mypy runs one invocation
over every `plugins/*/` file; two files sharing a basename with no package path (plugin dirs carry
hyphens) is a hard `Duplicate module named X` error. `pc-core` keeps the bare name as the home
module; each consumer's copy is prefixed.

## 3. Widen the checksum hook's trigger

`hygiene/pre-commit/extras/plugin-repo.yaml`, the `check-vendor-checksum` `files:` regex — add the
new basenames (source name + every `pc_<plugin>_<name>`) so an edit to any copy fires the hook.

## 4. Ship the bootstrap change

Commit the three files above, open a PR, merge. Nothing has reached the plugin repos yet — this is
the source + the mapping only.

## 5. Distribute into `pinky-agentic-plugins`

From a `pinky-bootstrap` checkout on `main` (post-merge):

```bash
uv run pinky distribute --repo pinky-agentic-plugins
```

`distribute_vendor` writes each copy to its `VENDOR_MAP` target and regenerates
`.vendor-manifest.json`. It also regenerates `.pre-commit-config.yaml` and — the trap —
**rewrites `pyproject.toml`'s `[tool.uv] exclude-newer` to today minus 3 days**, which desyncs
`uv.lock` and breaks `--locked` in CI.

In the `pinky-agentic-plugins` working tree:

```bash
git checkout pyproject.toml           # drop the exclude-newer rewrite — renewing it is a separate gesture
git add plugins/**/pc_*<name>.py .pre-commit-config.yaml
prek run generate-docs --all-files    # the README file tree still lists the old names
prek run --all-files                  # green
```

- `.vendor-manifest.json` is **git-ignored** — do not stage it. It is a local-dev drift guard only
  (`check-vendor-checksum` is a clean no-op in CI, where no manifest exists).
- `pinky distribute --commit` stages only `DISTRIBUTED_PATHS` (`.pre-commit-config.yaml`, CI
  workflows, `scripts/hooks/`…), **not** the vendored `.py` copies — those are authored-location
  files in the consumer repo, stage them by hand.

## 6. Wire the consumer

Whatever imports the lib, in each plugin that got a copy:

```python
sys.path.insert(0, str(Path(__file__).parent))       # or .parent.parent for hooks/branch-policy/
from pc_<plugin>_<name> import thing                  # bare import of the local copy
```

Commit, PR, merge.

## Editing a vendored lib later

Never edit a copy in `pinky-agentic-plugins` directly — `check-vendor-checksum` blocks it locally,
and the next `pinky distribute` overwrites it. Edit `hygiene/vendor/<name>.py` here, then re-run
step 5.
