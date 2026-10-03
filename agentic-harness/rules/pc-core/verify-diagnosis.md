---
_load_conditions:
  - "if a card, ticket or ADR you are about to act on states a cause or an absence, or you are about to rely on an unmeasured premise"
---
# A written diagnosis is a hypothesis, not a finding

A card, ticket or ADR often arrives with a **cause** already written down, and a plan built on top
of it. A plan derived from a wrong cause treats a symptom, and does so confidently — the document's
own framing supplies the confirmation.

## Mechanical detection

The document states a **cause** or, more dangerously, an **absence**: "if X is missing", "nothing
mechanizes Y", "no test covers W". Absence claims are the highest-risk class: cheap to write,
expensive to check, and nobody notices when they're wrong.

## Rule

Before executing the plan, isolate the causal claim and **test it in one command** — `command -v`,
the tool's own check mode, a `find`/`ls`, an existing `--check-*` flag. Then:

- **Claim holds** → execute the plan as written.
- **Claim falls** → rewrite the whole document (not just the offending section), re-derive the plan
  from the real cause, and say plainly the original diagnosis was wrong.

If verifying the claim takes more than a couple of commands, it's a research task in its own right —
scope it as one rather than assuming it.

## Applies to your own reasoning too

Same failure without any document: an argument whose premise is a half-sentence nobody measured
("those repos have no test suite anyway"). Verify the premise before it decides a placement, an
exclusion, or a scope — especially when the premise is what makes the conclusion convenient.
