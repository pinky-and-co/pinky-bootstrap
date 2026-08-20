# Kanban — markdown board, agent-maintained
*Update date : 2026-07-28 11:29*

The workspace carries a file-based kanban at `_KANBAN/` (workspace root, cross-repo). It is the live
state of the work: **epic = chantier**, **story = the chantier spec**, **task = a card** that moves
between columns. It replaces a ticketing tool for this workspace, and it works because **you, the
agent, maintain it reliably** — the user stays the decider, the clerical layer is automated. Why that
inversion is the differentiator: `_KANBAN/_REFERENCE.md` § Kanban.

## Maintain the board PROACTIVELY — design requirement #1

Do not wait for "create a card" or "move it to done". Surface the board update as part of the work.

- **Capture → card.** When the user surfaces a new task, idea, or request, write a card for it
  (`0-ideas/` if not yet scoped, `1-todo/` if scoped and committed) — without being asked.
- **Select → commit.** `2-selected-for-dev/` is the commitment point: the user moves a scoped card
  there, in priority order, when it's ready for a session. **The card IS the prompt.** Selecting is a
  USER decision by default; the agent may *propose* a selection, never select unasked.
- **Progress → move.** A session running `/chantier NNNN` takes the FIRST card in
  `2-selected-for-dev/` and moves it to `3-in-progress/`; finished and verified → `4-done/`.
  Moving = `mv` between column folders.
- **End of session → handoff.** Before context runs out or the session ends, update the in-progress
  card's handoff section so the next session resumes cleanly (handoff lives *in the card*).

### The handoff has two layers

- **Narrative (yours).** Prose in the in-progress card — state, decisions, next step. Your job, and
  the part that matters.
- **Auto block (the `Stop` hook).** `.claude/hooks/stop_handoff.py` maintains a managed
  `<!-- auto-handoff:start … end -->` block at the bottom of in-progress cards **whose scope matches
  the session's repo**, with the mechanical state (branch, uncommitted files, recent commits),
  whenever a turn ends with a dirty git tree. Non-blocking and idempotent — **never hand-edit between
  the markers** (it gets overwritten).
- **Anti-secrets, both layers.** The hook scrubs secret-shaped strings; the narrative must follow the
  same directive — never put secrets, credentials or internal URLs in a handoff.
- **Card scope — `**Repos:**` line, mandatory when moving to `3-in-progress`.** Add
  `**Repos:** <repo-name>[, <repo-name>…]` right under `**Statut:**`. It is the anti-cross-contamination
  filter: the hook only writes the auto block into cards declaring the session's repo (legacy
  fallback: the existing block's repo). A card declaring nothing gets no auto block — a wrong
  breadcrumb is worse than none. Kanban-only work → `**Repos:** —` (never matches).

## Convention

```
_KANBAN/
├── INDEX.md                         ← cross-chantier board (read at session start)
├── _FACTS.md                        ← durable facts (also in auto-memory)
├── _REFERENCE.md                    ← conventions / decisions
└── CHANTIER{NNNN}-<slug>/
    ├── <SPEC>.md                    ← the story (why / scope / architecture)
    ├── 0-ideas/                     ← chantier-local ideas, not yet scoped
    ├── 1-todo/                      ← scoped + committed
    ├── 2-selected-for-dev/          ← commitment point — user-ordered, next session takes the FIRST card
    ├── 3-in-progress/               ← active — the card carries its handoff
    └── 4-done/                      ← done (airlock) → fold the "why" into the story/ADR, then purge
```

- **Chantier = objective, not a repo.** One chantier can span several repos.
- **One card = one deliverable worth a multi-session handoff.** Micro-steps = a checklist *inside* the card.
- **Lifecycle:** `0-ideas` → (scoping) → `1-todo` → `2-selected-for-dev` → `3-in-progress` → `4-done` → archive.
- **A scoped idea becomes a `1-todo` card** (or a bullet in the story) and leaves `0-ideas/`.
- **`2-selected-for-dev` is the engagement column, not a queue to batch-fill.** Selection order =
  priority order. Absent for most dormant chantiers — created on demand, never pre-created empty.
- **`4-done` is an airlock, and archiving is the AGENT's job** (same proactivity as the rest of the
  board, never the user's chore): once the card's decision/rationale is folded into the story or an
  ADR of the real repo (there is no git here — the story IS the selective archive), `mv` it to
  `_KANBAN/_ARCHIVE/CHANTIER{NNNN}-done/`. Do it at session end, or when `/chantier` flags a non-empty
  `4-done/`. A card not yet folded stays in `4-done/` — folding first, always.

## Card dating — mandatory

Every card carries a date on its `**Statut:**` line. The user retrieves ideas **by date**, not by title.

| Column | Suffix to add | Example |
|--------|--------------|---------|
| `0-ideas` | `· surfacé YYYY-MM-DD` | `**Statut:** idea · surfacé 2026-06-18` |
| `1-todo` | `· scopé YYYY-MM-DD` | `**Statut:** todo · scopé 2026-06-17` |
| `2-selected-for-dev` | `· sélectionné YYYY-MM-DD` | `**Statut:** todo · sélectionné 2026-07-05` |
| `3-in-progress` | `· en-cours depuis YYYY-MM-DD` | `**Statut:** in-progress · en-cours depuis 2026-06-24` |
| `4-done` | replace `done` with `done (YYYY-MM-DD)` | `**Statut:** done (2026-06-23)` |

**Add the date suffix when creating the card — not retroactively.** When moving a card, update only
the relevant marker (e.g. add `· scopé` moving `0-ideas` → `1-todo`).

`_KANBAN/` cards are **exempt from the `doc_conventions` update-date tag** (`_*` paths). This
per-column dating rule is kanban-specific — it does not derive from the general `.md` convention.

## Card tier — the model floor

Every card declares the **minimum** model tier its work needs, on a `**Tier:**` line right under
`**Statut:**` (and under `**Repos:**` when present):

```
**Tier:** fast | default | thorough
```

- **It is a floor, never a ceiling.** Running a `fast` card on `thorough` wastes tokens; running a
  `thorough` card on `fast` produces a decision paid for several sessions later. That asymmetry is
  the whole point of the field — it exists to prevent the second case, not to optimise the first.
- **The agent fills it at scoping** (`0-ideas` → `1-todo`), like the rest of the clerical layer.
  **Mandatory from `2-selected-for-dev`** — the commitment point, same rule as `**Repos:**` for
  `3-in-progress`. Missing on a selected card → propose one and say why, never guess silently.
- **Tiers name tiers, never model ids.** The tier → model mapping lives in the profile's `models:`
  block and is rendered in CLAUDE.md § Model routing — one place to change when the lineup moves.
- **Heterogeneous card → tier the checklist items.** A card mixing mechanical work and arbitration
  would otherwise take the max and drift to `thorough` everywhere, which turns the field into noise.
  Set the card tier on the *bulk* of the work and override the outliers inline:

  ```
  - [ ] (thorough) arbitrer le placement du hook
  - [ ] renommer les constantes          ← inherits the card tier
  ```

  An item's own tier wins for that item only.

`/chantier` acts on it when it takes a card — see the command's step 6.

## Card filiation — what a card serves

Every card declares what it serves, on a `**Sert:**` line right under `**Statut:**` (and under
`**Repos:**` / `**Tier:**` when present):

```
**Sert:** packager-pinky-workspace     ← the objective or parent card (its filename, without `.md`)
**Sert:** —                            ← autonomous, an assumed side-quest
```

- **Why:** a hand-maintained "critical path" list on a parent card (enumerating what blocks it) is a
  centralized list — it drifts the moment a listed card moves, closes, or gets superseded elsewhere.
  A card declaring what it serves makes the critical path a **render**, derived from the board,
  instead of a list someone has to keep in sync. Same inversion as the agent/command/rule/hook
  contributor model (ADR-0058 to 0062): an artefact declares what it needs or serves, nobody
  enumerates artefacts elsewhere.
- **Mandatory from `0-ideas`** — the pile-up ("est-ce que je peux ignorer ça ?") happens at the idea
  stage, so that's where the field has to answer it. Earlier than `**Repos:**` (mandatory at
  `3-in-progress`) and `**Tier:**` (mandatory at `2-selected-for-dev`) — this field's job is
  triage, not execution readiness, so it starts sooner.
- **Value is a card filename (without `.md`), never free text.** A free-text objective ("packaging
  goal") can't be checked against a real card and rots into an unverifiable label. `—` is the one
  special value, for a genuine standalone side-quest.
- **Mono-valued.** A card serving two objectives is not yet a resolved case — don't design for it
  ahead of it actually happening.
- **`/chantier` renders the filiation** in its report — cards grouped by what they serve, `—` folded
  into a single count rather than listed. See the command's step 5.

## Orgs — one workspace, several mounted orgs (ADR-0015)

The workspace is **multi-org**. An org is a GitHub organization mirrored locally, and it owns three
coordination artefacts under a single root:

| Artefact | What it holds |
|---|---|
| `_KANBAN/` | the board — chantiers and cards |
| `_AGENT_LOG/` | the narrative journal (below) |
| `_corpus-*/` | the org's knowledge corpus |

**The org root is not where its repos live.** Repos are always local to the workspace and identified
by the org's own repo-name glob (`<org-prefix>-*`); only the coordination surface is mounted, and it
may sit on a drive shared with other people. Roots are resolved from the machine-local
`.pinky/config.txt` (key `kanban_roots_local`, comma-separated) — the nearest root by proximity, plus
every root it declares. Never committed, never synced: each machine has its own mount points. It was
its own `kanban-roots.txt` until ADR-0069; a residual copy is no longer read, and the hook says so
loudly rather than silently declaring zero boards.

**A shared org root is a replication boundary** — everything inside it lands on every machine that
mounts it. **No secret goes anywhere inside a shared root**; secrets stay outside (local-only /
`.env`). Rationale and full model: ADR-0015. Instance-specific values (provider, root names, mount
points): the profile's private rules.

## Cross-agent log — `_AGENT_LOG/`

Several agents touch the same orgs (Claude Code here and on another machine, Cortex, Claude.ai).
`_AGENT_LOG/` is the async channel between their sessions: the **narrative** trace of what a session
did — decisions taken, what was left open. It is **cross-chantier by nature**, which is exactly what
no card can hold: a card's handoff carries the state of one deliverable, this carries what a whole
session did, including work that moved no card at all.

- **Read it at session start**, alongside the board — the most recent entries of every mounted org,
  listed by `/chantier`'s auto-context. Skipping it is how you redo or contradict another agent's
  work. The listing is capped by recency rather than cut at a fixed number of days: a hook that
  writes a managed block may not call the clock (`hook-output-invariants.md`), and each entry's date
  is in its filename anyway — so an org whose journal has gone quiet stays visible instead of
  silently dropping off.
- **Write the trace into the org whose board carries the chantier you worked on.** A session that
  touched two orgs writes in both.
- **One file per (date, agent)**, append-only — never two writers on one file (anti-conflict rule for
  a synced-drive transport).
- **The filename must carry the emitter**: `YYYY-MM-DD_claude-code-<agent_identity>.md`, where
  `<agent_identity>` is the key of that name in `<workspace root>/.pinky/config.txt`
  (machine-local, gitignored). Without it, two people running Claude Code against a shared org root
  target the same path on the same day, and the drive resolves that as a conflict copy.
- Never log secrets, credentials or internal URLs.

**Not the only thing in `_AGENT_LOG/`.** Cortex writes a per-session **transfer manifest** there
(`YYYYMMDD_HHMISS_CORTEX_SESSION.md`, format in `providers/cortex/CORTEX.md`): the file list for the
user to download, plus the card moves Cortex cannot perform itself. One per session by design — the
per-(date, agent) rule above does not apply to it. The two artefacts coexist; they are not variants
of each other.

## Boundaries

- The kanban holds the **actionable and evolving** (chantiers / remaining work / ideas).
- **Durable facts** (user profile, `feedback_*` conventions, contract constraints) stay in Claude Code
  **auto-memory** — not here. `_FACTS.md` is a human-readable mirror of those facts.
- Don't fold IDE context into a card — a file open in the editor is not a task (see the IDE rule).
