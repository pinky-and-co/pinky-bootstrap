"""Pytest config for the engine suite — marker registration + the CI-parity recipe.

The repo ships no pyproject.toml (it is classed `python-lint`, not a package), so there is no
`[tool.pytest.ini_options]` slot to declare custom markers in. Registering `needs_private_corpus`
here keeps `pytest --strict-markers` clean and documents, in one place, what the public CI checkout
cannot cover (a test asserting a value of the private `pinky` profile, absent from `corpus-public`).

## Reproducing CI locally — neutralise BOTH ambient axes, not one

A CI checkout is poorer than the author's machine along two independent axes. Simulating only one
gives a false green: that is exactly how 4 tests shipped red to CI on 2026-07-24 (a run neutralising
the corpus alone passed locally, then failed the moment CI ran).

1. **The private corpus sibling** `_corpus-pinky` is never cloned by an Action
   → `CORPUS_ROOT=corpus-public`.
2. **External CLIs are not on the runner's PATH** — `prek`, `detect-secrets`, and friends are
   installed on the author's machine. A test that reaches `run_distribution` (rather than
   `distribute` alone) hits its Class B gate: missing tooling → `sys.exit(1)`, for a reason having
   nothing to do with what the test asserts. Stub the boundary (`_prek_install`,
   `_ensure_secrets_baseline`) rather than expecting the binaries — they talk to the outside world,
   so faking them is exactly what `tests.md` allows.

The honest local reproduction strips the PATH down to the interpreter:

    CORPUS_ROOT=corpus-public PATH=/usr/bin:/bin pytest

A stripped PATH is what makes axis 2 visible; without it the run stays green locally and red on CI.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "needs_private_corpus: asserts a value of a private profile absent from a public CI "
        "checkout (auto-skipped there via skipif) — see card ci-tests-absente-sur-le-moteur",
    )
