---
paths:
  - "**/*.py"
  - "**/stored_procedures/**"
  - "**/tasks/**"
_load_conditions:
  - "if you are writing, modifying or reviewing Snowpark code, a stored procedure or a task"
---
# Snowpark Python conventions

## Runtime — a managed platform, not a server you own

- No temp files/connections to clean up: the SP runs inside Snowflake's managed runtime, not a
  process you provision or tear down.
- Don't hand-roll logging or error reporting. The platform traces a SQL error automatically,
  according to the session's configured `LOG_LEVEL` — a bare `try/except` around SQL calls to
  "make sure it gets logged" is redundant.

## Lazy evaluation — nothing runs until an action

A `DataFrame` transformation (`.filter()`, `.select()`, `.with_column()`, `.join()`, ...) only
builds a query plan — it does not touch Snowflake. Only an **action** (`.collect()`, `.count()`,
`.show()`, `.write.save_as_table()`, returning it as the SP result) sends SQL and executes.

- **Written order ≠ execution order.** Two independent transformation chains defined one after the
  other in the code are not guaranteed to run in that sequence — only their actions are ordered
  (and only relative to each other, not to the transformations that feed them). If step B must see
  the effect of step A (e.g. B reads a table A just wrote), A needs an explicit action before B is
  defined, not just to appear earlier in the file.
- **A condition passed to `.filter()`/`.with_column()` is not per-row Python** — unlike a pandas
  `.apply(lambda row: ...)`, it builds a SQL expression once, at definition time. Python-side
  side effects (a `print`, a counter increment) inside that expression don't run per row, and may
  not run at all if the optimizer doesn't need that branch.

## Typing — general Python rule, sharper stakes here

Annotate every `Session`/`DataFrame`/`Column` variable and return type explicitly — not a
Snowpark-specific rule (it's `minimal-code`'s general expectation), but the payoff is higher here:
the API surface is large (`DataFrame`/`Column` methods chain deep), and autocomplete only works if
the type checker knows what a variable is at each step.

## Session handling

- A stored procedure handler receives its `Session` as a parameter — never instantiate one inside it.

## DataFrame conventions

- **No inline SQL** — build queries with the DataFrame API (`session.table()`, `.filter()`,
  `.join()`, ...), never a hand-written string passed to `session.sql(...)`. A DataFrame object
  already covers the operation is a stronger signal than "it would also work as a string".
- Use `cache_result()` when a DataFrame is consumed more than once
- Prefer `left_anti` join over subquery for "not exists" patterns
- Always alias columns explicitly after joins to avoid ambiguity
- Use `lit()` for literal values in column expressions — never bare Python values
