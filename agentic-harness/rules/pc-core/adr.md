---
paths:
  - "**/docs/adr/**"
_load_conditions:
  - "if you are adding, superseding or editing an ADR"
---
# docs/adr/ — Architecture Decision Records

One file per technical decision. Template below in English — the fixed convention (section labels,
`Status`/`Date` keys, filename slug), same register as this rule itself. The body prose follows the
`explanation` language of the repo's language policy instead (`fr` for this workspace), never
hardcoded here since each repo declares its own. Carries the same `title:`
frontmatter as `docs/explanation/`/`docs/reference/` files (see `doc-hygiene.md`) — the literal ADR
number, e.g. `title: "0003"`:

```markdown
---
title: "NNNN"
---
# ADR-NNNN — Title
Status: accepted | superseded by ADR-XXXX | deprecated
Date: YYYY-MM-DD

## Context
Why did this decision come up?

## Decision
What was decided?

## Consequences
Trade-offs accepted.
```

- Status is `accepted` by default.
- To reverse a decision: create a new ADR, set the old one to `superseded by ADR-XXXX`.
- Never edit a past ADR — append only.
- Add a pointer to `docs/index.md` when creating a new ADR (skip on mkdocs repos — generated).
- Write the ADR in the same turn as the technical decision it records, not only when documenting a
  rejection — don't wait to be asked.
