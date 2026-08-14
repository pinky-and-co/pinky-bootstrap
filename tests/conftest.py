"""Pytest config for the engine suite — marker registration + the CI-parity recipe.

The repo ships no pyproject.toml (it is classed `python-lint`, not a package), so there is no
`[tool.pytest.ini_options]` slot to declare custom markers in. Registering `needs_private_corpus`
here keeps `pytest --strict-markers` clean and documents, in one place, what the public CI checkout
cannot cover (a test asserting a value of the private `pinky` profile, absent from `corpus-public`).

## Reproducing CI locally — neutralise ALL THREE ambient axes, not one

A CI checkout is poorer than the author's machine along THREE independent axes. Simulating only some
gives a false green: that is exactly how 4 tests shipped red to CI on 2026-07-24 (a run neutralising
the corpus alone passed locally, then failed the moment CI ran), and again on 2026-08-07 — axes 1 and
2 neutralised, axis 3 forgotten, two tests red on the runner.

1. **The private corpus sibling** `_corpus-pinky` is never cloned by an Action
   → `CORPUS_ROOT=corpus-public`.
2. **The instance config is OUTSIDE the repo** — since ADR-0065 it lives at
   `<workspace root>/.pinky/config.txt`, gitignored, carrying `repo_globs`, `internal_dep_prefix`,
   `default_profile`. A CI checkout has no `.pinky/` above it, so the resolver finds none and each
   key degrades to a graceful empty/None. A test needing one of those values must pin it itself
   (see the autouse fixtures in `test_product_scaffold.py` / `test_mypy_hermetic_deps.py`), never
   inherit it from the machine — which it WOULD locally, where `.pinky/` sits two levels up.
3. **External CLIs are not on the runner's PATH** — `prek`, `detect-secrets`, and friends are
   installed on the author's machine. A test that reaches `run_distribution` (rather than
   `distribute` alone) hits its Class B gate: missing tooling → `sys.exit(1)`, for a reason having
   nothing to do with what the test asserts. Stub the boundary (`_prek_install`,
   `_ensure_secrets_baseline`) rather than expecting the binaries — they talk to the outside world,
   so faking them is exactly what `tests.md` allows.

The honest local reproduction copies the tree to a path with NO `.pinky/` above it (a `git clone` to
a clean path does this by construction, and also dodges the `[]`-in-path pytest issue — see
pytest.ini), and strips the PATH down to the interpreter:

    rsync -a --exclude='.git' <repo>/ /tmp/ci-sim/
    cd /tmp/ci-sim && CORPUS_ROOT=corpus-public PATH=/usr/bin:/bin pytest

Axis 2 used to need an explicit `rm -f` of the gitignored file, because it lived INSIDE the repo and
rsync copied it. Now that it lives at the workspace root, a copy outside the workspace loses it for
free — the poorer environment is the default instead of something to remember.

A stripped PATH is what makes axis 3 visible; without it the run stays green locally and red on CI.
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "needs_private_corpus: asserts a value of a private profile absent from a public CI "
        "checkout (auto-skipped there via skipif) — see card ci-tests-absente-sur-le-moteur",
    )
