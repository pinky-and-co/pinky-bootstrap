"""Card `capacites-ambiantes-non-declarees` (checklist item 3): `npx wrangler login` installed 13
skills into `~/.claude/skills/` with nothing in the moteur aware of it. `--check-machine` makes the
one probeable class of ambient capability (skills/plugins on disk) visible — it never tries to
reconcile them against declared `machine_capabilities` (a different vocabulary), and it is never a
gate: the card's scope is visibility, not elimination.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402


def _write_plugins_manifest(claude_dir: Path, plugins: dict) -> None:
    manifest = claude_dir / "plugins" / "installed_plugins.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"version": 2, "plugins": plugins}), encoding="utf-8"
    )


def test_no_skills_no_plugins_is_silent_and_zero(tmp_path, capsys):
    assert setup.check_machine(tmp_path) == 0
    out = capsys.readouterr().out
    assert "(none found)" in out


def test_finds_skills_on_disk(tmp_path, capsys):
    (tmp_path / "skills" / "wrangler").mkdir(parents=True)
    (tmp_path / "skills" / "cloudflare").mkdir(parents=True)
    # A stray FILE directly under skills/ must not be mistaken for a skill (only dirs count).
    (tmp_path / "skills" / "README.md").write_text("x", encoding="utf-8")

    count = setup.check_machine(tmp_path)

    out = capsys.readouterr().out
    assert "skill   wrangler" in out
    assert "skill   cloudflare" in out
    assert "README.md" not in out
    assert count == 2


def test_finds_plugins_from_the_installed_ledger(tmp_path, capsys):
    _write_plugins_manifest(
        tmp_path,
        {
            "terraform@claude-plugins-official": [{"scope": "user"}],
            "skill-creator@claude-plugins-official": [{"scope": "user"}],
        },
    )

    count = setup.check_machine(tmp_path)

    out = capsys.readouterr().out
    assert "plugin  terraform@claude-plugins-official" in out
    assert "plugin  skill-creator@claude-plugins-official" in out
    assert count == 2


def test_corrupt_plugins_manifest_degrades_to_empty_not_a_crash(tmp_path, capsys):
    manifest = tmp_path / "plugins" / "installed_plugins.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{ not json", encoding="utf-8")

    assert setup.check_machine(tmp_path) == 0


def test_declared_capabilities_are_listed_as_trusted(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        setup.machine_check, "MACHINE_CAPABILITIES", frozenset({"cortex", "pypi"})
    )
    setup.check_machine(tmp_path)
    out = capsys.readouterr().out
    assert "✓ cortex" in out
    assert "✓ pypi" in out


def test_no_declared_capabilities_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(setup.machine_check, "MACHINE_CAPABILITIES", frozenset())
    setup.check_machine(tmp_path)
    out = capsys.readouterr().out
    assert "(none declared)" in out


def test_never_a_gate_regardless_of_ambient_count(tmp_path):
    """The card's own scope is visibility, not elimination — an ambient skill found is never an
    error; only the caller (--check-machine in cli.py) decides the exit code, and it's always 0."""
    (tmp_path / "skills" / "wrangler").mkdir(parents=True)
    count = setup.check_machine(tmp_path)
    assert count > 0  # sanity: something WAS found
    # check_machine itself never raises / calls sys.exit — the absence of an exception here IS
    # the assertion.


def test_quiet_suppresses_all_output_but_still_counts(tmp_path, capsys):
    (tmp_path / "skills" / "wrangler").mkdir(parents=True)
    count = setup.check_machine(tmp_path, quiet=True)
    assert count == 1
    assert capsys.readouterr().out == ""
