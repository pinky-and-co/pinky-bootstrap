"""Pytest config for the engine suite — the CI-parity recipe.

## Reproducing CI locally

**External CLIs are not on the runner's PATH** — `prek`, `detect-secrets`, and friends are
installed on the author's machine. A test that reaches `run_distribution` (rather than
`distribute` alone) hits its Class B gate: missing tooling → `sys.exit(1)`, for a reason having
nothing to do with what the test asserts. Stub the boundary (`_prek_install`,
`_ensure_secrets_baseline`) rather than expecting the binaries — they talk to the outside world,
so faking them is exactly what `tests.md` allows.

The honest local reproduction strips the PATH down to the interpreter:

    PATH=/usr/bin:/bin pytest

A stripped PATH is what makes this axis visible; without it the run stays green locally and red
on CI.
"""
