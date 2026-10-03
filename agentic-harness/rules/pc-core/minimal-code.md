---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.sh"
_load_conditions:
  - "if you are about to write or modify code"
---
# Minimal-code convention

Understand the problem first. Then, **before generating code**, walk this ladder top-down and stop at
the first rung that satisfies the need — the best code is the code you don't write:

1. **Does this need to exist?** (YAGNI) — drop speculative features, options nobody asked for, premature abstraction.
2. **Already in the codebase?** — reuse before adding. Grep first; a second helper that does the same thing is debt.
3. **In the standard library?** — prefer stdlib over a new dependency.
4. **A native platform feature?** — a browser API, a framework built-in, an HTML element — before a hand-rolled one.
5. **An already-installed dependency?** — extend what's pulled in before adding another.
6. **Can it be one line?** — a comprehension, a built-in call, a one-line expression.
7. **Only then**: the minimum viable implementation — and no more.

This filters *after* understanding the problem; it never replaces understanding it, and it never trades
away correctness for brevity.

## Non-negotiable — minimal ≠ unsafe

"Minimal" governs *volume*, never these. They stay in scope whatever the ladder says:

- input validation and error handling
- security (no leaked secrets, no injection, least-agency)
- the test that proves the change (see `tests.md`)

## Scope & overrides

- **Specific overrides general** — a domain rule may tighten or relax a rung; the more specific wins.
  See `docs/explanation/rules-scope-and-precedence.md`.
- **Pre + post, same conviction** — this rule constrains *before* writing; a review pass surfaces
  friction *after*. They are the two halves of the anti-over-engineering stance, not duplicates.
