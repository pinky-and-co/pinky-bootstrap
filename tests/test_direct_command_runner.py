#!/usr/bin/env python3
"""Tests for hygiene/vendor/direct_command_runner.py — run with: python3 -m pytest tests/test_direct_command_runner.py"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = (
    Path(__file__).parent.parent / "hygiene" / "vendor" / "direct_command_runner.py"
)

GRAMMAR = {
    "forms": [
        {"match": [], "emit": ["--root", "{env:CLAUDE_PROJECT_DIR}"]},
        {"match": ["--all"], "emit": ["--root", "{env:CLAUDE_PROJECT_DIR}"]},
        {"match": [{"re": r"[\w.]+"}], "emit": ["--repo", "{0}"]},
        {"match": ["multi", {"re": r"[\w.]+", "repeat": True}], "emit": ["{*}"]},
    ]
}


def _script(tmp_path, body='echo "$@"', name="fixture.sh"):
    path = tmp_path / name
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)
    return path


def _run(tmp_path, args, script=None, grammar=None, timeout=5, raw_stdin=None):
    script = script or _script(tmp_path)
    event = json.dumps({"command_args": args, "cwd": str(tmp_path)})
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--script",
            str(script),
            "--interpreter",
            "bash",
            "--grammar",
            json.dumps(GRAMMAR) if grammar is None else grammar,
            "--timeout",
            str(timeout),
        ],
        input=event if raw_stdin is None else raw_stdin,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0
    return proc.stdout


def test_conforming_args_block_with_script_output(tmp_path):
    out = json.loads(_run(tmp_path, "myrepo"))
    assert out["decision"] == "block"
    assert out["reason"] == "--repo myrepo"
    assert set(out) == {"decision", "reason"}


def test_empty_args_match_the_empty_form_and_expand_env_fallback(tmp_path):
    out = json.loads(_run(tmp_path, ""))
    assert out["reason"] == f"--root {tmp_path}"


def test_repeat_spec_takes_several_tokens_and_splices(tmp_path):
    out = json.loads(_run(tmp_path, "multi a b c"))
    assert out["reason"] == "multi a b c"


def test_no_matching_form_is_silent(tmp_path):
    assert _run(tmp_path, "two words") == ""


def test_leading_dash_never_matches_a_regex_spec(tmp_path):
    assert _run(tmp_path, "--force") == ""


def test_injection_attempts_are_silent_and_never_executed(tmp_path):
    sentinel = tmp_path / "pwned"
    for bad in (
        f"; touch {sentinel}",
        f"$(touch {sentinel})",
        f"`touch {sentinel}`",
        f"a\ntouch {sentinel}",
        f"a && touch {sentinel}",
        f"a | touch {sentinel}",
        f"a > {sentinel}",
    ):
        assert _run(tmp_path, bad) == "", bad
    assert not sentinel.exists()


def test_nonzero_exit_is_silent(tmp_path):
    assert _run(tmp_path, "x", script=_script(tmp_path, "exit 3")) == ""


def test_timeout_is_silent(tmp_path):
    assert _run(tmp_path, "x", script=_script(tmp_path, "sleep 5"), timeout=1) == ""


def test_missing_script_is_silent(tmp_path):
    assert _run(tmp_path, "x", script=tmp_path / "nope.sh") == ""


def test_malformed_stdin_and_grammar_are_silent(tmp_path):
    assert _run(tmp_path, "x", raw_stdin="not json") == ""
    assert _run(tmp_path, "x", grammar="{oops") == ""
    assert _run(tmp_path, "x", grammar=json.dumps({"forms": [{"match": ["x"]}]})) == ""


def test_empty_script_output_is_reported_explicitly(tmp_path):
    out = json.loads(_run(tmp_path, "x", script=_script(tmp_path, "true")))
    assert out["reason"] == "(no output)"


def test_timeout_kills_grandchildren_and_returns_promptly(tmp_path):
    import time

    sentinel = tmp_path / "late"
    body = f"(sleep 3; touch {sentinel}) &\nsleep 30"
    start = time.monotonic()
    assert _run(tmp_path, "x", script=_script(tmp_path, body), timeout=1) == ""
    assert time.monotonic() - start < 3
    time.sleep(3)
    assert not sentinel.exists()


def test_chatty_stderr_and_large_stdout_do_not_deadlock(tmp_path):
    body = "head -c 300000 /dev/zero | tr '\\0' e >&2\nhead -c 300000 /dev/zero | tr '\\0' o"
    out = json.loads(_run(tmp_path, "x", script=_script(tmp_path, body), timeout=10))
    assert len(out["reason"]) == 300000


def test_non_utf8_output_is_silent(tmp_path):
    assert _run(tmp_path, "x", script=_script(tmp_path, "printf '\\377\\376'")) == ""


def test_nonexistent_cwd_is_silent(tmp_path):
    script = _script(tmp_path)
    event = json.dumps({"command_args": "myrepo", "cwd": str(tmp_path / "gone")})
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--script",
            str(script),
            "--interpreter",
            "bash",
            "--grammar",
            json.dumps(GRAMMAR),
        ],
        input=event,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert (proc.returncode, proc.stdout) == (0, "")


def test_nonzero_exit_after_partial_stdout_is_silent(tmp_path):
    assert _run(tmp_path, "x", script=_script(tmp_path, "echo partial\nexit 1")) == ""


def test_quoted_and_equals_leading_dash_never_match(tmp_path):
    for bad in ('"-x"', "'--k=v'", "--k=v"):
        assert _run(tmp_path, bad) == "", bad


def test_set_project_dir_wins_over_the_cwd_fallback(tmp_path):
    script = _script(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--script",
            str(script),
            "--interpreter",
            "bash",
            "--grammar",
            json.dumps(GRAMMAR),
        ],
        input=json.dumps({"command_args": "", "cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "CLAUDE_PROJECT_DIR": "/somewhere/else"},
    )
    assert json.loads(proc.stdout)["reason"] == "--root /somewhere/else"


def _bare(args, event, tmp_path):
    return subprocess.run(
        [sys.executable, str(RUNNER), *args],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )


def test_argparse_errors_exit_zero_and_stay_silent(tmp_path):
    proc = _bare([], {"command_args": ""}, tmp_path)
    assert (proc.returncode, proc.stdout) == (0, "")


def test_invalid_interpreter_is_silent(tmp_path):
    script = _script(tmp_path)
    proc = _bare(
        [
            "--script",
            str(script),
            "--interpreter",
            "perl",
            "--grammar",
            json.dumps(GRAMMAR),
        ],
        {"command_args": "", "cwd": str(tmp_path)},
        tmp_path,
    )
    assert (proc.returncode, proc.stdout) == (0, "")


def test_direct_exec_and_python3_interpreters_run(tmp_path):
    grammar = json.dumps({"forms": [{"match": [], "emit": ["hi"]}]})
    event = {"command_args": "", "cwd": str(tmp_path)}
    direct = _bare(
        ["--script", str(_script(tmp_path)), "--grammar", grammar], event, tmp_path
    )
    assert json.loads(direct.stdout)["reason"] == "hi"
    py = tmp_path / "p.py"
    py.write_text("import sys; print('py', *sys.argv[1:])")
    proc = _bare(
        ["--script", str(py), "--interpreter", "python3", "--grammar", grammar],
        event,
        tmp_path,
    )
    assert json.loads(proc.stdout)["reason"] == "py hi"


def test_quoted_metacharacter_is_silent(tmp_path):
    assert _run(tmp_path, "'a;b'") == ""


def test_unset_env_placeholder_is_silent(tmp_path):
    grammar = json.dumps({"forms": [{"match": [], "emit": ["{env:NOPE_UNSET}"]}]})
    assert _run(tmp_path, "", grammar=grammar) == ""


def test_non_ascii_output_survives_a_strict_ascii_stdout(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--script",
            str(_script(tmp_path, "echo 'é✅'")),
            "--interpreter",
            "bash",
            "--grammar",
            json.dumps({"forms": [{"match": [], "emit": []}]}),
        ],
        input=json.dumps({"command_args": "", "cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "ascii:strict"},
    )
    assert (proc.returncode, json.loads(proc.stdout)["reason"]) == (0, "é✅")


def _child_session_id(tmp_path, event_extra, ambient=None):
    """What `CLAUDE_CODE_SESSION_ID` a script started by the runner sees for this event."""
    script = _script(
        tmp_path, 'echo "${CLAUDE_CODE_SESSION_ID-absent}"', name="probe.sh"
    )
    env = {"PATH": "/usr/bin:/bin"}
    if ambient is not None:
        env["CLAUDE_CODE_SESSION_ID"] = ambient
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--script",
            str(script),
            "--interpreter",
            "bash",
            "--grammar",
            json.dumps({"forms": [{"match": [], "emit": []}]}),
        ],
        input=json.dumps({"command_args": "", "cwd": str(tmp_path), **event_extra}),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    return json.loads(proc.stdout)["reason"]


def test_runner_forwards_the_event_session_id_to_the_child(tmp_path):
    assert _child_session_id(tmp_path, {"session_id": "sess-42"}) == "sess-42"


def test_runner_event_session_id_wins_over_the_ambient_variable(tmp_path):
    out = _child_session_id(tmp_path, {"session_id": "sess-42"}, ambient="ambient")
    assert out == "sess-42"


def test_runner_leaves_the_environment_untouched_without_a_session_id(tmp_path):
    assert _child_session_id(tmp_path, {}) == "absent"
    assert _child_session_id(tmp_path, {}, ambient="ambient") == "ambient"


@pytest.mark.parametrize("bad", ["", None, 7, ["x"]])
def test_runner_ignores_a_session_id_that_is_not_a_non_empty_string(tmp_path, bad):
    assert _child_session_id(tmp_path, {"session_id": bad}) == "absent"


def _path_grammar():
    return json.dumps(
        {"forms": [{"match": [{"re": r"/[\w./-]+"}], "emit": ["--repo", "{0}"]}]}
    )


def test_at_prefixed_relative_path_is_resolved_against_cwd(tmp_path):
    cwd = tmp_path / "a" / "b"
    cwd.mkdir(parents=True)
    event = json.dumps({"command_args": "@../repo/", "cwd": str(cwd)})
    out = json.loads(_run(tmp_path, "", grammar=_path_grammar(), raw_stdin=event))
    assert out["reason"] == f"--repo {tmp_path / 'a' / 'repo'}"


def test_at_prefixed_absolute_path_loses_trailing_slash(tmp_path):
    out = json.loads(_run(tmp_path, "@/x/y/", grammar=_path_grammar()))
    assert out["reason"] == "--repo /x/y"


@pytest.mark.parametrize("args", ["@", "@~/repo"])
def test_bare_at_and_tilde_words_stay_unresolved(tmp_path, args):
    assert _run(tmp_path, args, grammar=_path_grammar()) == ""


def test_word_without_at_is_unchanged(tmp_path):
    assert _run(tmp_path, "../repo", grammar=_path_grammar()) == ""
