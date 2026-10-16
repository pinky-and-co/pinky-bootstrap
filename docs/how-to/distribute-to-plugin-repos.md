# How to distribute the hygiene to the workspace repos
*Update date : 2026-10-15 21:08*

```bash
pinky repo distribute (--repo <name> | --all) [--dry-run] [--yes] [--commit]
```

pinky-bootstrap is the single source of every repo's hooks, pre-commit config, CI workflows and
vendored shared libs (`hygiene/`). `distribute` copies that source into one repo or every repo of
the workspace. A distributed file is owned by pinky-bootstrap: edit the source, then distribute —
an edit made in the consumer repo is overwritten by the next run.

## Run it

1. **Preview one repo first.** `pinky repo distribute --repo pinky-core --dry-run` prints the plan,
   file by file, and writes nothing.
2. **Apply.** The same command without `--dry-run` prints the same plan, then asks
   `Apply N file change(s) in M repo(s)? [y/N]`. Only `y` applies. Nothing is written before that
   answer.
3. **Every repo.** `--all` instead of `--repo`. Without either, the command refuses to run.
4. **Unattended.** In a non-interactive shell (CI, a script, an agent) the prompt cannot be
   answered: the run exits 1 unless `--yes` (`-y`) is passed.
5. **Commit in the same pass.** `--commit` commits the distributed files in each repo, one commit
   per repo (`🔧 chore: adopt pinky-bootstrap centralized hooks distribution`), with the repo's
   own hooks running — see [Commit what was distributed](#commit-what-was-distributed).

After a real run, the drift check runs on the same repos; residual drift exits non-zero. A missing
CLI tool (`prek`, `detect-secrets`) also exits non-zero, after distributing everything else.

## What lands in a repo

Which files a repo receives depends on its **extras**, derived from its layout (never from a name
list):

| Extra | When |
|---|---|
| base | every repo |
| `python` | has a `pyproject.toml` |
| `snowflake` | Python repo whose `pyproject.toml` names snowflake/snowpark in its dependencies (`[project]`, optional, `[dependency-groups]`) or `[project].keywords` — never in a comment or description |
| `web` | has a `package.json` and no `pyproject.toml` |
| `python-lint` | ships `.py` files but has neither `pyproject.toml` nor `package.json` |
| `plugin-repo` | has a `.claude-plugin/` directory (additive to the others) |

### Hooks and pre-commit

| File | Source | Notes |
|---|---|---|
| `.pre-commit-config.yaml` | `hygiene/pre-commit/base.yaml` + `extras/<extra>.yaml` | assembled per repo |
| `scripts/hooks/*` | `hygiene/hooks/` | only the scripts this repo's config references |
| `scripts/hooks/docs_identity.json` | the group's docs identity | |
| `scripts/hooks/badges.toml`, `ruff.toml` | `hygiene/hooks/`, `hygiene/pre-commit/hooks-ruff.toml` | |
| `.gitleaks.toml`, `.gitattributes` | `hygiene/pre-commit/` | |
| `.darglint` | constant in `setup/precommit.py` | `python` extra only; not drift-checked |
| `.secrets.baseline` | `detect-secrets scan` | created once if missing, never overwritten |

The run ends with `prek install` (pre-commit and commit-msg hooks) in each repo.

### CI workflows

| Workflow | Who gets it |
|---|---|
| `prek.yml` | every repo — the hook suite plus `pr-required-on-main`, the only guard against a direct push to `main` |
| `ci.yml` | repos with a `requires-python` pin — build and tests |
| `windows.yml` | repos in `CI_WINDOWS_PILOT` |
| `worker.yml` | repos declaring a D1 binding in `wrangler.jsonc` |
| `install-walkthrough.yml` | pinky-bootstrap itself |

Templates live in `hygiene/ci/`. Per-repo install and test commands come from
`CI_INSTALL_OVERRIDES`, `CI_TESTS_OVERRIDES` and `CI_NO_LOCK_REPOS` in `setup/precommit.py`.

### Shared files

These files also belong to the repo, so `distribute` edits them in place rather than replacing
them:

| File | What changes |
|---|---|
| `pyproject.toml` | `[tool.uv]` gets `exclude-newer` and `required-version`; the rest is untouched |
| `.python-version` | aligned on `requires-python` |
| `README.md` | the generated sections between markers |
| `docs/index.md` | regenerated when the repo has a generated index |
| `.claude/settings.pinky.json` | created with `{"branch_workflow": null}` if missing, never overwritten |

### Vendored libs

A few small libs are shared by plugins that cannot import each other at runtime. Their source is
`hygiene/vendor/`; `VENDOR_MAP` in `setup/precommit.py` maps each one to its copies. A repo gets a
copy only where the target's directory already exists — today, pinky-agentic-plugins only. Each
run also writes `.vendor-manifest.json` (path → sha256 of the copied content).

The `check-vendor-checksum` hook (`plugin-repo` extra) rejects a commit whose copy no longer
matches the manifest: a hand-edited copy would be silently overwritten by the next run. The
manifest is committed — an ignored manifest fails the hook too, since CI would otherwise check
nothing.

## Add a vendored lib

1. Put the source in `hygiene/vendor/<name>.py`.
2. Add `"<name>.py": ["plugins/<plugin>/hooks/<copy>.py", ...]` to `VENDOR_MAP`.
3. Add each copy's filename to the `files:` regex of `check-vendor-checksum` in
   `hygiene/pre-commit/extras/plugin-repo.yaml` — the hook only runs when a matching file is
   staged.
4. `pinky repo distribute --repo pinky-agentic-plugins --commit`, then open a PR in that repo.

## Commit what was distributed

`--commit` stages:

- every distributed path (`DISTRIBUTED_PATHS`: pre-commit config, hooks, gitleaks, gitattributes,
  darglint, the CI workflows);
- `.vendor-manifest.json` and every copy it lists;
- the shared files — **only those that were clean before the run**, so an edit in progress is
  never swept into a distribution commit.

A repo whose own hooks block the commit is reported `BLOCKED`; its files stay staged. Fix the
hook failure and commit by hand.

## Check for drift without distributing

```bash
pinky repo drift
```

Compares every repo's hook scripts, `.pre-commit-config.yaml`, `ci.yml` and `prek.yml` with the
source. Writes nothing. It also reports orphaned scripts — `distribute` never deletes a file, so a
script dropped from the source stays in the repo until removed by hand.

## AGENTS.md

Workspace and group AGENTS.md are regenerated by the `pc-autodiscovery` plugin at session start.
