---
paths:
  - "plugins/**/hooks/**"
---
# Hook output invariants — no context bloat
*Update date : 2026-07-04 19:50*

Harness hooks run every turn. A careless one silently wastes tokens — and the waste is *invisible* to
the hook layer itself (a hook cannot see the running token count or a context re-injection). So the
guard is a **build-time invariant**, not a runtime monitor.

## The two rules

1. **A persisted managed block must be a pure function of state.**
   Any hook that writes a managed block into a file (an `<!-- auto-… -->` region, marked in code by a
   `BLOCK_START` constant) must build that block from state alone — **no wall-clock, no nonce, no
   counter**. Rationale: the file often already sits in the agent's context; if the block changes when
   nothing substantive did, the hook rewrites the file and the harness **re-injects the whole file**
   next turn (~1K tokens per read file, per turn — the auto-handoff timestamp incident, 2026-07-04).

2. **Hook output is bounded.** Cap any list/blob a hook writes or prints (cf. `MAX_FILES` in
   `stop_handoff.py`). An unbounded dump is the other bloat vector.

## Enforcement (test-first)

- Each managed-block builder carries a purity test — see
  `tests/test_stop_handoff.py::test_build_block_is_pure_function_of_state_no_timestamp`.
- A generic guard scans every harness hook for wall-clock in a managed-block writer:
  `tests/test_hook_output_invariants.py`. A new hook that reintroduces the churn fails CI before it ships.

## Live visibility (complement, not a substitute)

The build-time invariant stops the *class*; for day-to-day awareness use the native signal — the
`statusline.py` bar shows live context-window usage (from the transcript's last `usage` record) and
session cost, and `/context` breaks down what fills the window. Wall-clock output belongs there (an
ephemeral status line), **never** in a file the agent re-reads.
