---
_load_conditions:
  - "if you are writing a code comment, a rule, a doc file, a card or a memory entry"
---
# No narrated history — in code, rules, or docs

A comment, rule, or doc file describes **current state and actionable instruction**. It is read
every session, in full, at a real token cost — a sentence about *how the current content came to be*
costs exactly as much as a sentence about *what to do*, but only the second one earns its place on a
repeat read. Applies as much to a code comment ("used to work differently, changed for X") as to a
rule or doc file.

## The tell

A sentence whose subject is the artefact's own editing history, not the topic it's about:

- "Merged on DATE from three near-identical rules that shared a preamble..."
- "This used to say X, changed because Y."
- "Renamed from `old_name` on DATE (ADR-NNNN)."

None of these help apply the code or the rule *today*. They help someone reconstructing *why* it
looks the way it does — that job already has a home.

## Where each kind of information actually lives

| Information | Where it lives |
|---|---|
| The intent | name, typing, docstring, test |
| The rejected alternative | an ADR (the only info that's in neither the code nor git) |
| The chronology | git |
| A comment | whatever fits none of the three — so a rare, **deliberate deviation**, not a recap |

## Rule

Provenance/rationale for an artefact's own shape lives in the commit message and, when the decision
matters beyond this one file, an ADR. Never re-narrate it in the artefact's ongoing body. If a fact
about the past is load-bearing for a CURRENT constraint (not just trivia about how it evolved), fold
it into the constraint itself as the *why*, phrased for the present — not as a dated changelog entry.

**Exception, not a loophole**: citing a past *incident* as concrete evidence a constraint is real,
not decorative, survives (a measured audit backing a test-coverage rule, a named regression backing a
build-time guard). The test: does the sentence justify a rule that still applies, or does it just
narrate the artefact's own paperwork? The first survives, the second gets cut.

Same failure when writing a new card, ADR, or memory entry: don't append "this used to say X" as
prose that has to be re-read on every future visit. If the history matters, it's already in the
commit that changed the file — link it, don't retype it.
