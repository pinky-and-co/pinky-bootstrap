---
paths:
  - "**/docs/**/*.md"
_load_conditions:
  - "if you are writing or modifying documentation"
---
# Documentation conventions — doc files

Scoped to `docs/` trees. `README.md`, `AGENTS.md` and `CLAUDE.md` are out of scope.

## Update date tag

Every **hand-edited** `.md` file carries a freshness tag on the line **immediately after its `# Title`**:

```
# Title
*Update date : 2026-05-25 16:31*
```

Anchored to the H1, not to line 2 — a file may carry YAML frontmatter above its title.

**Rule: after editing any `.md` file, read the file modification timestamp with
`stat -f "%Sm" -t "%Y-%m-%d %H:%M" <file>` and update this tag accordingly.** Every write, even a
one-line fix.

**Exempt:** `_*` prefixed paths, `.claude/`, and files whose dynamic content is generator-owned
(badges, tagline, generated indexes) — git history is the freshness signal instead.

## `title:` frontmatter — short display name, mechanically consumed

Every file under `docs/explanation/`, `docs/reference/` (excluding `api/`, `generated/`,
`studio-managed/`) and `docs/adr/` carries a `title:` field in a `---`-delimited YAML frontmatter
block, above the `# Title` line — for an ADR it's the literal number (`title: "0003"`, see `adr.md`):

```
---
title: DAG
---
# DAG — Task orchestration
*Update date : 2026-06-12 10:00*
```

Short, terse, no repo name. Add the field — a missing one is silently skipped, don't work around it.

## Conflict resolution — most recent wins

When two `.md` files contain contradictory information:

1. The file with the more recent `*Update date :*` is authoritative.
2. Flag the conflict to the user: which files, what the contradiction is, which date wins.
3. Propose a reconciliation strategy — update the stale file, or consolidate into a single source of truth.

## DRY documentation

**Before writing in any `.md`, read the repo's doc routing surface first** to know what already
exists — if the subject is covered, write in the indicated file, never create a new one.

- **Repos with a mkdocs site**: the routing surface is the README's generated `## Documentation`
  section plus the nav that builds itself from the filesystem.
- **Repos without a site**: `docs/index.md` is a hand-maintained light index, one line per doc file.

```markdown
- [explanation/1-design.md](explanation/1-design.md) — architecture, principes, couverture objets. Not for: decisions (→ adr/)
```

**Rule: when creating or deleting a doc file, update `docs/index.md` in the same edit** (skip on
mkdocs repos — the generator owns it).

Do not duplicate content across `.md` files — reference the authoritative file by path instead of
copying it. If you spot duplicated content while working, flag it as a reconciliation candidate; do
not silently update both copies.

## Doc phases

**Build phase (pre-V1)** — two obligations only: `docs/index.md` (agent entry point, one line per
file) and `docs/adr/` (one file per technical decision, append-only). No Diátaxis folders required.

**Stable phase (post-V1)** — full Diátaxis structure below. `docs/adr/` stays the source of truth for
decisions; Diátaxis files **reference** ADRs by path, never duplicate them.

```
docs/
├── index.md             ← always present (build + stable)
├── adr/                 ← always present (build + stable)
├── tutorials/           ← learning-oriented: step-by-step walkthroughs
├── how-to/              ← task-oriented: solve a specific problem
├── reference/           ← lookup: API, schemas, config, specs
│   ├── api/             ← mkdocstrings stubs — hand-written once, content generated at build time
│   ├── generated/       ← code-generated only — never hand-edit
│   └── studio-managed/  ← studio-managed only — never hand-edit
└── explanation/         ← understanding: design decisions, trade-offs, scope, roadmap
```

A file belongs to exactly one folder. Never mix types in the same file. Empty folders are allowed —
they signal what documentation is still missing.
