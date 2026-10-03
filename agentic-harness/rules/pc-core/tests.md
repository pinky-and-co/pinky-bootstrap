---
paths:
  - "**/*.py"
  - "**/*.ts"
  - "**/*.tsx"
  - "**/*.js"
  - "**/*.jsx"
  - "**/*.sh"
_load_conditions:
  - "if you are fixing a bug, extending or modifying code, or writing tests"
---
# Test convention

## Bug workflow

1. Write a failing test that reproduces the bug
2. Fix the code
3. Confirm the test passes

Never fix first and test after — the test is the proof the fix is correct. For a new feature: write
tests that define done, then implement. For a refactor: tests pass before and after, no behaviour
change.

## Assertions on generated output — every generator needs an oracle

When a test asserts on **generated output** (SQL/DDL, CSS, HTML, a rendered config or prompt), a
substring assertion proves almost nothing: it passes on the correct output *and* on a wrong one.

**Rule.** For every function that builds output — `*_sql`, `*_ddl`, `*_clause`, `build_*`,
`render_*`, `generate_*` — at least one test must assert **equality on the whole output**:

```python
# weak — true for the correct key MY_DAG$ROOT and for the bare MY_DAG that broke all SKIP gating
assert "MY_DAG" in dag.build_when_clause(task)

# strong — the entire string is pinned, ordering and quoting included
assert dag.build_when_clause(task) == (
    "SYSTEM$GET_PREDECESSOR_RETURN_VALUE('MY_DAG$ROOT') != 'SKIP'"
)
```

Fragment assertions stay welcome *in addition* to the oracle, never as the only thing covering a
generator. **Name the generator so the ratchet can see it** — a function that builds output but
isn't named with one of the suffixes/prefixes above escapes detection silently; rename it, don't
widen the matcher. Negative assertions (`assert "EXPIRE AFTER" not in ddl`) are exempt — they prove
an absence, which can't freeze a bug the way a positive fragment does. If the output isn't
deterministic, fix that in the test (freeze the clock, the tmp path, the ordering) rather than
falling back to fragments.

**Not a rare pattern**: an audit across several Python lib repos found the large majority of
fragment-tested generators had no oracle at all — the seed for this rule, not a hypothetical.

## Never mock the class that carries the contract under test

A weak assertion still exercises the real subject. A **mock that replaces the subject** removes it
from the test entirely — no assertion, however strong, can recover it.

**Rule.** Fake only what talks to the outside world — network, filesystem, clock, a paying API. The
class whose behaviour or construction contract the test claims to check stays **real**. When a test
double is unavoidable, it must be a *subclass* of the real thing, never a stand-in shaped like it.

The tell: a fake defined as a bare class with the same method names as the SDK/library type. It
answers every call, so it can never reject an argument the real class requires — exactly the failure
it was supposed to catch.

**Detection question, before writing any double:** *if the real class started rejecting how we
construct or call it, would this test notice?* If no, the double is covering the subject, not a
boundary. A suite that passes throughout while a whole feature path can never run in prod is the
failure mode this guards against — a test that structurally cannot fail.
