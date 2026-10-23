"""`hygiene/vendor/pending_user_action.py` — the session-scoped queue of
actions only the user can do (a slash command the CLI parses before a turn).

Vendored source of truth, distributed into pc-autodiscovery/hooks and
pc-kanban/chantier. `require`/`resolve`/`surface`/`pending`/`clear_surfaced`/
`clear_all` are the library; the `__main__` CLI wraps them for skill bodies.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "hygiene" / "vendor"))
import pending_user_action as pua


def _isolated_env(home: Path, **extra: str) -> dict[str, str]:
    """A subprocess env whose home dir is `home` on either platform.

    `Path.home()` reads `HOME` on POSIX and `USERPROFILE` on Windows; Windows
    Python also needs `SystemRoot` on `PATH`-stripped envs. Set all three so the
    CLI's `STATE_DIR` lands under `home` wherever the suite runs.
    """
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "PATH": os.environ.get("PATH", ""),
    }
    if "SYSTEMROOT" in os.environ:
        env["SystemRoot"] = os.environ["SYSTEMROOT"]
    env.update(extra)
    return env


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(pua, "STATE_DIR", tmp_path / "state")
    return "sess-1"


# ── library ────────────────────────────────────────────────────────────────


def test_require_then_pending_returns_the_message(store):
    pua.require(store, "reload-plugins", "/reload-plugins")
    assert pua.pending(store) == {"reload-plugins": "/reload-plugins"}


def test_require_same_key_twice_replaces_never_duplicates(store):
    pua.require(store, "goal", "/goal old")
    pua.require(store, "goal", "/goal new")
    assert pua.pending(store) == {"goal": "/goal new"}


def test_require_default_surfaced_is_false_in_the_stored_entry(store):
    pua.require(store, "goal", "/goal x")
    assert json.loads(pua._queue_path(store).read_text()) == {
        "goal": {"message": "/goal x", "surfaced": False}
    }


def test_require_surfaced_true_is_stored_on_the_entry(store):
    pua.require(store, "goal", "/goal x", surfaced=True)
    assert json.loads(pua._queue_path(store).read_text()) == {
        "goal": {"message": "/goal x", "surfaced": True}
    }


def test_require_same_key_twice_replaces_surfaced_too(store):
    pua.require(store, "goal", "/goal old", surfaced=True)
    pua.require(store, "goal", "/goal new")
    assert json.loads(pua._queue_path(store).read_text()) == {
        "goal": {"message": "/goal new", "surfaced": False}
    }


def test_resolve_drops_one_key_and_is_a_noop_when_absent(store):
    pua.require(store, "a", "x")
    pua.require(store, "b", "y")
    pua.resolve(store, "a")
    pua.resolve(store, "missing")
    assert pua.pending(store) == {"b": "y"}


def test_surface_returns_every_message_in_order_and_empties_the_queue(store):
    pua.require(store, "rename", "/rename slug")
    pua.require(store, "reload-plugins", "/reload-plugins")
    assert pua.surface(store) == ["/rename slug", "/reload-plugins"]
    assert pua.pending(store) == {}
    assert pua.surface(store) == []


def test_pending_on_a_fresh_session_is_empty(store):
    assert pua.pending(store) == {}


def test_pending_tolerates_a_corrupt_queue_file(store):
    (pua.STATE_DIR).mkdir(parents=True)
    pua._queue_path(store).write_text("{not json")
    assert pua.pending(store) == {}


def test_pending_coerces_a_legacy_bare_string_entry(store):
    """A queue entry written before the `surfaced` field existed (bare
    `{key: message}`) is coerced to `surfaced=False`, not dropped — a stale
    plugin cache (this file is vendored into two independently-versioned
    plugins) can write this shape even after this version is installed
    elsewhere, and the message must still surface, not vanish silently."""
    pua.STATE_DIR.mkdir(parents=True)
    pua._queue_path(store).write_text(json.dumps({"reload-plugins": "/reload-plugins"}))
    assert pua.pending(store) == {"reload-plugins": "/reload-plugins"}


def test_require_after_a_legacy_entry_saves_the_coerced_shape(store):
    """The first write back to a legacy-shaped file (any `require`/`resolve`
    triggering `_save`) upgrades the whole queue to the current shape."""
    pua.STATE_DIR.mkdir(parents=True)
    pua._queue_path(store).write_text(json.dumps({"reload-plugins": "/reload-plugins"}))
    pua.require(store, "goal", "/goal x")
    assert json.loads(pua._queue_path(store).read_text()) == {
        "reload-plugins": {"message": "/reload-plugins", "surfaced": False},
        "goal": {"message": "/goal x", "surfaced": False},
    }


def test_surface_coerces_a_legacy_bare_string_entry(store):
    pua.STATE_DIR.mkdir(parents=True)
    pua._queue_path(store).write_text(json.dumps({"reload-plugins": "/reload-plugins"}))
    assert pua.surface(store) == ["/reload-plugins"]
    assert pua.pending(store) == {}


def test_clear_all_empties_and_is_a_noop_without_a_file(store):
    pua.require(store, "a", "x")
    pua.clear_all(store)
    assert pua.pending(store) == {}
    pua.clear_all(store)  # no file now — must not raise


def test_two_sessions_have_independent_queues(store, monkeypatch):
    pua.require(store, "a", "x")
    pua.require("sess-2", "b", "y")
    assert pua.pending(store) == {"a": "x"}
    assert pua.pending("sess-2") == {"b": "y"}


def test_clear_surfaced_drops_only_surfaced_entries(store):
    pua.require(store, "goal", "/goal x", surfaced=True)
    pua.require(store, "reload-plugins", "/reload-plugins")
    pua.clear_surfaced(store)
    assert pua.pending(store) == {"reload-plugins": "/reload-plugins"}


def test_clear_surfaced_is_a_noop_without_a_file(store):
    pua.clear_surfaced(store)  # no file yet — must not raise
    assert pua.pending(store) == {}


def test_clear_surfaced_does_not_rewrite_the_file_when_nothing_is_surfaced(store):
    pua.require(store, "reload-plugins", "/reload-plugins")
    before = pua._queue_path(store).stat().st_mtime_ns
    pua.clear_surfaced(store)
    after = pua._queue_path(store).stat().st_mtime_ns
    assert before == after
    assert pua.pending(store) == {"reload-plugins": "/reload-plugins"}


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli(tmp_path, *args, session="cli-sess"):
    return subprocess.run(
        [sys.executable, str(pua.__file__), *args],
        capture_output=True,
        text=True,
        env=_isolated_env(tmp_path, CLAUDE_CODE_SESSION_ID=session),
        check=False,
    )


def test_cli_require_then_pending_roundtrips(tmp_path):
    _cli(tmp_path, "require", "reload-plugins", "/reload-plugins")
    out = _cli(tmp_path, "pending")
    assert out.stdout == "reload-plugins\t/reload-plugins\n"


def test_cli_require_default_surfaced_is_false_in_the_stored_file(tmp_path):
    _cli(tmp_path, "require", "goal", "/goal x")
    queue_path = (
        tmp_path / ".claude" / "pinky" / "plugin-scope" / "cli-sess.pending.json"
    )
    assert json.loads(queue_path.read_text()) == {
        "goal": {"message": "/goal x", "surfaced": False}
    }


def test_cli_require_surfaced_flag_is_stored_on_the_entry(tmp_path):
    _cli(tmp_path, "require", "goal", "/goal x", "--surfaced")
    queue_path = (
        tmp_path / ".claude" / "pinky" / "plugin-scope" / "cli-sess.pending.json"
    )
    assert json.loads(queue_path.read_text()) == {
        "goal": {"message": "/goal x", "surfaced": True}
    }


def test_cli_resolve_removes_the_entry(tmp_path):
    _cli(tmp_path, "require", "k", "msg")
    _cli(tmp_path, "resolve", "k")
    assert _cli(tmp_path, "pending").stdout == ""


def test_cli_without_session_id_env_errors(tmp_path):
    result = subprocess.run(
        [sys.executable, str(pua.__file__), "pending"],
        capture_output=True,
        text=True,
        env=_isolated_env(tmp_path),
        check=False,
    )
    assert result.returncode == 2
    assert "CLAUDE_CODE_SESSION_ID" in result.stderr


def test_cli_unknown_verb_errors(tmp_path):
    result = _cli(tmp_path, "frobnicate")
    assert result.returncode == 2
    assert "usage:" in result.stderr
