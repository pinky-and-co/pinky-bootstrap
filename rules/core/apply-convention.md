# Applying one convention to N targets

Repeating the same change across repos, modules or files is **dispatched work**, never a loop in
this chat and never a batch of prompts for the user to paste. Copying one prompt into N sessions
turns the person into a relay with nothing to decide — the cost is theirs, the value is nobody's.

## Dispatch, by what the work actually needs

**The work is deterministic** — same edit, same command, mechanical per target → **a script**.
Discover the targets, loop, report per target. No model in the loop. `pc-commit`'s
`scripts/bulk_commit.sh` is the working shape: everything mechanical in bash, the model called once
per *group of identical diffs*, not once per target.

**Each target needs judgment** — the change depends on what is already there → **one `Agent` call
per target**, in parallel. Each prompt must be self-contained: the agent does not inherit this
conversation, and a subagent does not inherit the body of the skill that spawned it. Pass absolute
paths and resolved values, never a variable or a "see this file".

Most jobs are the first kind wearing the costume of the second. Ask what actually varies per target
before reaching for agents: often only one string does.

## Sequence — the pattern first, the repetition after

1. **Do it for real on one witness target**, in this session, at the session's own tier. That is
   where the judgment lives, and it is what turns a convention into a diff someone can point at.
2. **Then dispatch the repetition**, with that diff as the specification — forked, on the cheapest
   tier that can execute it (`haiku`). The children apply a known change; they do not re-decide it.

Never dispatch before the pattern exists. N agents each re-deriving the same decision is N chances
to derive it differently, paid at the highest tier — the exact failure the fan-out is meant to avoid.

## Constraints

- **Targets must be independent.** If B needs A's result, it is a sequence, not a fan-out — do it
  sequentially and say so.
- **4 concurrent at most**, 15 minutes each. Past that, report the target as failed; never retry
  blindly.
- **Report per target**, and keep the states distinct — done / partial / skipped / failed. A run
  that claims success while leaving targets on the floor is worse than one that fails loudly.

## The no-loop rule

Do not iterate targets one by one in this chat, "just to get started". Either it is dispatchable, or
the scope is wrong and needs saying. Working through fifteen targets conversationally burns the
context that the fifteenth one needed.
