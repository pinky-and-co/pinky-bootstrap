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
    (via `enable_at_project`, `set_status_lines`, ...) would append tmp
    paths to the real ledger. Redirect it here for the whole suite. A test that inspects the ledger
    still monkeypatches `STATE_FILE_PATH` to its own location — the later setattr wins.
    """
    import setup.state_file as state_file

    monkeypatch.setattr(
        state_file, "STATE_FILE_PATH", tmp_path / "pinky-install-state.json"
    )


@pytest.fixture(autouse=True)
def _isolate_plugin_catalog(tmp_path, monkeypatch):
    """No test may read the machine's real `~/.claude` marketplaces — a bare name's
    candidates come from the known catalogs, so the real ones would leak into the answer. A test
    that needs catalogs publishes synthetic ones with `publish_marketplaces`."""
    import setup.plugin_catalog as plugin_catalog

    monkeypatch.setattr(plugin_catalog, "CLAUDE_DIR", tmp_path / "no-claude-dir")


@pytest.fixture
def publish_marketplaces(tmp_path, monkeypatch):
    """`publish(<marketplace> -> [plugin names])` registers synthetic marketplaces — a
    `known_marketplaces.json` plus one `.claude-plugin/marketplace.json` each — under a tmp
    `CLAUDE_DIR`."""
    import json

    import setup.plugin_catalog as plugin_catalog

    claude_dir = tmp_path / "synthetic-claude"

    def publish(catalogs: dict[str, list[str]]) -> Path:
        known = {}
        for marketplace, names in catalogs.items():
            checkout = tmp_path / "checkouts" / marketplace
            (checkout / ".claude-plugin").mkdir(parents=True, exist_ok=True)
            (checkout / ".claude-plugin" / "marketplace.json").write_text(
                json.dumps({"plugins": [{"name": n} for n in names]}), encoding="utf-8"
            )
            known[marketplace] = {"installLocation": str(checkout)}
        (claude_dir / "plugins").mkdir(parents=True, exist_ok=True)
        (claude_dir / "plugins" / "known_marketplaces.json").write_text(
            json.dumps(known), encoding="utf-8"
        )
        monkeypatch.setattr(plugin_catalog, "CLAUDE_DIR", claude_dir)
        return claude_dir

    return publish
