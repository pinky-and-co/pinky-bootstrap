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

import sys
from pathlib import Path

import pytest

# conftest imports before the test modules — each of which does this same insert to reach `setup.*`.
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolate_installer_ledger(tmp_path, monkeypatch):
    """No test may write the machine's real `~/.claude/pinky-install-state.json`.

    `state_file.STATE_FILE_PATH` is a module-level path resolved at import from `Path.home()` —
    patching `Path.home` afterwards does not reach it, so every test that reaches `record_posed`
    (via `enable_plugin`, `set_status_lines`, `generate_agents_md`, ...) would append tmp paths
    to the real ledger. Redirect it here for the whole suite. A test that inspects the ledger
    still monkeypatches `STATE_FILE_PATH` to its own location — the later setattr wins.
    """
    import setup.state_file as state_file

    monkeypatch.setattr(
        state_file, "STATE_FILE_PATH", tmp_path / "pinky-install-state.json"
    )
