"""`setup/user_state.py` — the one-time move of the CLI's `~/.claude/` files under
`~/.claude/pinky/`, so an uninstall removes one directory and leaves nothing scattered.

The migration tests and the isolation fixtures alone may name the legacy `pinky-`-prefixed
locations; no CLI or documentation text does.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from setup import plugin_curated, state_file, user_state


@pytest.fixture
def fake_claude_dir(tmp_path, monkeypatch):
    """A temp `~/.claude` with the three current constants redirected under it — the layout
    `migrate()` sees, without touching the machine's real home."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    pinky_dir = claude_dir / "pinky"
    monkeypatch.setattr(state_file, "STATE_FILE_PATH", pinky_dir / "install-state.json")
    monkeypatch.setattr(
        plugin_curated, "USER_CURATED_PATH", pinky_dir / "curated-plugins.toml"
    )
    monkeypatch.setattr(user_state, "PLUGIN_SCOPE_DIR", pinky_dir / "plugin-scope")
    return claude_dir


def test_ledger_moves_with_identical_bytes_when_only_the_old_one_exists(
    fake_claude_dir,
):
    old = fake_claude_dir / "pinky-install-state.json"
    old.write_text(
        '{"k": {"key": "k", "path": "/x", "value": "v"}}\n', encoding="utf-8"
    )

    user_state.migrate()

    new = fake_claude_dir / "pinky" / "install-state.json"
    assert (
        new.read_text(encoding="utf-8")
        == '{"k": {"key": "k", "path": "/x", "value": "v"}}\n'
    )
    assert not old.exists()


def test_curated_list_moves_when_only_the_old_one_exists(fake_claude_dir):
    old = fake_claude_dir / "pinky-curated-plugins.toml"
    old.write_text("[[entries]]\n", encoding="utf-8")

    user_state.migrate()

    new = fake_claude_dir / "pinky" / "curated-plugins.toml"
    assert new.read_text(encoding="utf-8") == "[[entries]]\n"
    assert not old.exists()


def test_both_present_leaves_each_untouched(fake_claude_dir):
    old = fake_claude_dir / "pinky-install-state.json"
    new = fake_claude_dir / "pinky" / "install-state.json"
    new.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")

    user_state.migrate()

    assert old.read_text(encoding="utf-8") == "old"
    assert new.read_text(encoding="utf-8") == "new"


def test_legacy_plugin_scope_dir_is_deleted(fake_claude_dir):
    old = fake_claude_dir / "pinky-plugin-scope"
    (old / "shared").mkdir(parents=True)
    (old / "sess.json").write_text("{}", encoding="utf-8")

    user_state.migrate()

    assert not old.exists()
    assert not (fake_claude_dir / "pinky" / "plugin-scope").exists()


def test_legacy_plugin_scope_dir_is_deleted_even_when_the_new_one_exists(
    fake_claude_dir,
):
    new = fake_claude_dir / "pinky" / "plugin-scope"
    new.mkdir(parents=True)
    (new / "sess.json").write_text("{}", encoding="utf-8")
    old = fake_claude_dir / "pinky-plugin-scope"
    old.mkdir()

    user_state.migrate()

    assert not old.exists()
    assert (new / "sess.json").read_text(encoding="utf-8") == "{}"


def test_second_run_writes_and_removes_nothing(fake_claude_dir):
    (fake_claude_dir / "pinky-plugin-scope").mkdir()
    user_state.migrate()
    sentinel = fake_claude_dir / "pinky" / "install-state.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("{}", encoding="utf-8")

    user_state.migrate()

    assert sentinel.read_text(encoding="utf-8") == "{}"
    assert list(fake_claude_dir.iterdir()) == [fake_claude_dir / "pinky"]


def test_every_owned_path_resolves_under_pinky_dir(tmp_path):
    """Oracle for the three locations: with a fresh `HOME`, each module-level path resolves
    under `~/.claude/pinky/` — a subprocess so the import-time `Path.home()` reads the temp
    home, not the machine's."""
    env = {
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
    }
    if "SYSTEMROOT" in os.environ:
        env["SystemRoot"] = os.environ["SystemRoot"]
    code = (
        "from setup.state_file import STATE_FILE_PATH\n"
        "from setup.plugin_curated import USER_CURATED_PATH\n"
        "from setup.user_state import PLUGIN_SCOPE_DIR\n"
        "print(STATE_FILE_PATH)\n"
        "print(USER_CURATED_PATH)\n"
        "print(PLUGIN_SCOPE_DIR)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    pinky = tmp_path / ".claude" / "pinky"
    assert out.stdout.splitlines() == [
        str(pinky / "install-state.json"),
        str(pinky / "curated-plugins.toml"),
        str(pinky / "plugin-scope"),
    ]


def test_moved_then_migrated_again_leaves_content_and_mtime(fake_claude_dir):
    (fake_claude_dir / "pinky-install-state.json").write_text("{}", encoding="utf-8")
    user_state.migrate()
    new = fake_claude_dir / "pinky" / "install-state.json"
    before = (new.read_text(encoding="utf-8"), new.stat().st_mtime_ns)

    user_state.migrate()

    assert (new.read_text(encoding="utf-8"), new.stat().st_mtime_ns) == before


def test_curated_both_present_leaves_each_untouched(fake_claude_dir):
    old = fake_claude_dir / "pinky-curated-plugins.toml"
    new = fake_claude_dir / "pinky" / "curated-plugins.toml"
    new.parent.mkdir(parents=True)
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")

    user_state.migrate()

    assert old.read_text(encoding="utf-8") == "old"
    assert new.read_text(encoding="utf-8") == "new"


def test_pinky_dir_existing_as_a_file_does_not_raise(fake_claude_dir):
    (fake_claude_dir / "pinky").write_text("not a dir", encoding="utf-8")
    old = fake_claude_dir / "pinky-install-state.json"
    old.write_text("{}", encoding="utf-8")

    user_state.migrate()

    assert old.read_text(encoding="utf-8") == "{}"


def test_symlinked_legacy_scope_dir_is_unlinked_not_followed(fake_claude_dir, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep.json").write_text("{}", encoding="utf-8")
    legacy = fake_claude_dir / "pinky-plugin-scope"
    try:
        legacy.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    user_state.migrate()

    assert not legacy.is_symlink()
    assert (target / "keep.json").exists()


def test_cli_startup_runs_the_migration(fake_claude_dir):
    """`cli_pinky.main` reaches the real `migrate()` before dispatching — the first access of
    the ledger is a CLI run, so that is where the one-time move fires."""
    import setup.cli_pinky as cli_pinky

    old = fake_claude_dir / "pinky-install-state.json"
    old.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli_pinky.main(["directives", "E402"])
    assert excinfo.value.code in (0, None)
    assert not old.exists()
    assert (fake_claude_dir / "pinky" / "install-state.json").exists()


def test_setup_cli_startup_runs_the_migration(fake_claude_dir):
    """`setup.cli.main` runs the real `migrate()` right after parsing its arguments."""
    import setup.cli as cli

    old = fake_claude_dir / "pinky-curated-plugins.toml"
    old.write_text("[[entries]]\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--directives", "E402"])
    assert excinfo.value.code in (0, None)
    assert not old.exists()
    assert (fake_claude_dir / "pinky" / "curated-plugins.toml").exists()
