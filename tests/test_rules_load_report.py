"""rules_load_report.py — rule bytes injected per Claude Code actor, before vs after a cutover."""

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

TOOL = Path(__file__).parent.parent / "tools" / "rules_load_report.py"
_spec = importlib.util.spec_from_file_location("rules_load_report", TOOL)
rlr = importlib.util.module_from_spec(_spec)
sys.modules["rules_load_report"] = rlr
_spec.loader.exec_module(rlr)

# Le tz de référence se pose avec `time.tzset()`, appel POSIX sans équivalent Windows.
_tzset = pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset() est POSIX")

RULES = "/w/.claude/rules"
CONTENT = "/w/.claude/rules-content"


def _write(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _msg(ts: str) -> dict:
    return {"type": "user", "timestamp": ts, "message": {"content": "hi"}}


def _eager(ts: str, files: dict[str, str]) -> dict:
    return {
        "type": "attachment",
        "timestamp": ts,
        "attachment": {
            "type": "instructions",
            "files": [
                {"path": p, "type": "Project", "content": c} for p, c in files.items()
            ],
        },
    }


def _lazy(ts: str, path: str, content: str) -> dict:
    return {
        "type": "attachment",
        "timestamp": ts,
        "attachment": {
            "type": "nested_memory",
            "path": path,
            "content": {"path": path, "type": "Project", "content": content},
        },
    }


def _read(
    ts: str, tid: str, path: str, text: str, *, is_error: bool = False
) -> list[dict]:
    use = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": tid,
                    "name": "Read",
                    "input": {"file_path": path},
                }
            ]
        },
    }
    result = {
        "type": "user",
        "timestamp": ts,
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": "1\t" + text,
                    **({"is_error": True} if is_error else {}),
                }
            ]
        },
        "toolUseResult": {"type": "text", "file": {"filePath": path, "content": text}},
    }
    return [use, result]


def _agent(
    proj: Path, sid: str, aid: str, agent_type: str, entries: list[dict]
) -> None:
    base = proj / sid / "subagents"
    _write(base / f"agent-{aid}.jsonl", entries)
    (base / f"agent-{aid}.meta.json").write_text(
        json.dumps({"agentType": agent_type}), encoding="utf-8"
    )


def _report(tmp_path: Path, capsys, *extra: str) -> str:
    code = rlr.main(["--projects-dir", str(tmp_path), *extra])
    assert code == 0
    return capsys.readouterr().out


def test_scan_counts_eager_rules_but_not_claude_md(tmp_path):
    f = tmp_path / "s.jsonl"
    _write(
        f,
        [
            _eager(
                "2026-09-20T10:00:00Z",
                {"/w/CLAUDE.md": "x" * 100, f"{RULES}/a.md": "é" * 10},
            )
        ],
    )
    assert rlr.scan_transcript(f) == {f"{RULES}/a.md": ("session-start", 20)}


def test_scan_lazy_stub_and_content_read_are_distinct_loads(tmp_path):
    f = tmp_path / "s.jsonl"
    _write(
        f,
        [
            _lazy("2026-09-20T10:00:00Z", f"{RULES}/t.md", "stub"),
            *_read("2026-09-20T10:00:01Z", "t1", f"{CONTENT}/t.md", "full body"),
        ],
    )
    assert rlr.scan_transcript(f) == {
        f"{RULES}/t.md": ("lazy-stub-or-path", 4),
        f"{CONTENT}/t.md": ("content-read", 9),
    }


def test_scan_repeated_path_counts_once(tmp_path):
    f = tmp_path / "s.jsonl"
    _write(
        f,
        [
            _lazy("2026-09-20T10:00:00Z", f"{RULES}/t.md", "stub"),
            _lazy("2026-09-20T10:00:01Z", f"{RULES}/t.md", "stub"),
            _eager("2026-09-20T10:00:02Z", {f"{RULES}/t.md": "stub"}),
        ],
    )
    assert rlr.scan_transcript(f) == {f"{RULES}/t.md": ("lazy-stub-or-path", 4)}


def test_failed_read_is_not_counted_and_does_not_shadow_a_retry(tmp_path):
    f = tmp_path / "s.jsonl"
    _write(
        f,
        [
            *_read(
                "2026-09-20T10:00:00Z",
                "t1",
                f"{CONTENT}/t.md",
                "boom" * 5,
                is_error=True,
            ),
            *_read("2026-09-20T10:00:01Z", "t2", f"{CONTENT}/t.md", "full body"),
        ],
    )
    assert rlr.scan_transcript(f) == {f"{CONTENT}/t.md": ("content-read", 9)}


def test_scan_ignores_non_rule_reads_and_bad_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    _write(f, [*_read("2026-09-20T10:00:00Z", "t1", "/w/src/app.py", "code")])
    with f.open("a", encoding="utf-8") as fh:
        fh.write("not json\n")
    assert rlr.scan_transcript(f) == {}


@_tzset
def test_parse_bound_naive_is_local_time(monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    try:
        assert rlr.parse_bound("2026-10-03T21:00").isoformat() == (
            "2026-10-03T19:00:00+00:00"
        )
        assert rlr.parse_bound("2026-10-03T21:00Z").isoformat() == (
            "2026-10-03T21:00:00+00:00"
        )
    finally:
        monkeypatch.undo()
        time.tzset()


def test_windows_follow_first_timestamp_of_main_and_subagents_follow_parent(
    tmp_path, capsys
):
    proj = tmp_path / "pinky-x"
    _write(proj / "s1.jsonl", [_msg("2026-09-20T10:00:00Z")])
    _agent(
        proj,
        "s1",
        "a1",
        "pc-core:reviewer",
        [_eager("2026-10-05T10:00:00Z", {f"{RULES}/a.md": "x" * 50})],
    )
    _write(proj / "s2.jsonl", [_msg("2026-10-02T10:00:00Z")])
    out = _report(
        tmp_path,
        capsys,
        "--before",
        "2026-10-01T00:00Z",
        "--after",
        "2026-10-03T00:00Z",
    )
    assert "1 session(s) ignored (between bounds)" in out
    before = out.split("before\n")[1].split("\n\n")[0].splitlines()
    assert [r.split() for r in before[1:]] == [
        ["main", "1", "0", "0", "0", "0"],
        ["pc-core:reviewer", "1", "50", "50", "0", "0"],
    ]


@_tzset
def test_local_time_after_bound_is_converted(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Paris")
    time.tzset()
    try:
        proj = tmp_path / "pinky-x"
        # 18:30Z is 20:30 Paris: before the 21:00 local bound, so between bounds.
        _write(proj / "s1.jsonl", [_msg("2026-10-03T18:30:00Z")])
        # 19:30Z is 21:30 Paris: at or after the bound.
        _write(proj / "s2.jsonl", [_msg("2026-10-03T19:30:00Z")])
        out = _report(
            tmp_path,
            capsys,
            "--before",
            "2026-10-01T00:00",
            "--after",
            "2026-10-03T21:00",
        )
    finally:
        monkeypatch.undo()
        time.tzset()
    assert "1 session(s) ignored (between bounds)" in out
    after = out.split("after\n")[1].split("\n\n")[0]
    assert "main" in after
    assert "no session" not in after.splitlines()[1]


def test_bounds_are_half_open(tmp_path, capsys):
    proj = tmp_path / "pinky-x"
    _write(proj / "at_before.jsonl", [_msg("2026-10-01T00:00:00Z")])
    _write(proj / "at_after.jsonl", [_msg("2026-10-03T00:00:00Z")])
    out = _report(
        tmp_path,
        capsys,
        "--before",
        "2026-10-01T00:00Z",
        "--after",
        "2026-10-03T00:00Z",
    )
    # start == before is not "before"; start == after is "after".
    assert out.split("before\n")[1].splitlines()[1].split() == ["main", "no", "session"]
    assert out.split("after\n")[1].splitlines()[1].split()[:2] == ["main", "1"]
    assert "1 session(s) ignored (between bounds)" in out


def test_since_ignores_older_sessions_and_counts_them_in_the_note(tmp_path, capsys):
    proj = tmp_path / "pinky-x"
    _write(proj / "old.jsonl", [_msg("2026-09-01T10:00:00Z")])
    _write(proj / "kept.jsonl", [_msg("2026-09-20T10:00:00Z")])
    out = _report(tmp_path, capsys, "--since", "2026-09-10T00:00Z")
    assert out.split("before\n")[1].splitlines()[1].split()[:2] == ["main", "1"]
    assert out.endswith("note: 1 session(s) ignored (between bounds)\n")


def test_unknown_agent_type_has_its_own_row(tmp_path, capsys):
    proj = tmp_path / "pinky-x"
    _write(proj / "s1.jsonl", [_msg("2026-09-20T10:00:00Z")])
    base = proj / "s1" / "subagents"
    _write(
        base / "agent-a.jsonl",
        [_eager("2026-09-20T10:00:01Z", {f"{RULES}/a.md": "x" * 7})],
    )
    out = _report(tmp_path, capsys)
    rows = out.split("before\n")[1].split("\n\n")[0].splitlines()
    assert [r.split() for r in rows[1:]] == [
        ["main", "1", "0", "0", "0", "0"],
        ["unknown", "1", "7", "7", "0", "0"],
    ]


def test_empty_window_prints_no_session_and_delta_na(tmp_path, capsys):
    proj = tmp_path / "pinky-x"
    _write(proj / "s1.jsonl", [_eager("2026-09-20T10:00:00Z", {f"{RULES}/a.md": "x"})])
    out = _report(tmp_path, capsys)
    after_rows = out.split("after\n")[1].splitlines()
    assert after_rows[1].split() == ["main", "no", "session"]
    assert "n/a" in out.split("delta (after")[1]


def test_project_filter_excludes_other_projects(tmp_path, capsys):
    _write(tmp_path / "other" / "s1.jsonl", [_msg("2026-09-20T10:00:00Z")])
    out = _report(tmp_path, capsys)
    assert out.split("before\n")[1].splitlines()[1].split() == ["main", "no", "session"]


def test_full_report_on_small_fixture(tmp_path, capsys):
    proj = tmp_path / "pinky-x"
    _write(
        proj / "s1.jsonl",
        [
            _msg("2026-09-20T10:00:00Z"),
            _eager(
                "2026-09-20T10:00:01Z",
                {"/w/CLAUDE.md": "z", f"{RULES}/a.md": "x" * 100},
            ),
        ],
    )
    _agent(proj, "s1", "a1", "pc-core:reviewer", [_msg("2026-09-20T10:01:00Z")])
    _write(
        proj / "s2.jsonl",
        [
            _msg("2026-10-04T10:00:00Z"),
            _lazy("2026-10-04T10:00:01Z", f"{RULES}/t.md", "s" * 10),
            *_read("2026-10-04T10:00:02Z", "t1", f"{CONTENT}/t.md", "b" * 40),
        ],
    )
    _agent(proj, "s2", "a2", "pc-core:reviewer", [_msg("2026-10-04T10:01:00Z")])
    out = _report(
        tmp_path,
        capsys,
        "--before",
        "2026-10-01T00:00Z",
        "--after",
        "2026-10-03T21:00Z",
    )
    assert out == (
        "before\n"
        "actor             transcripts  avg rule bytes/transcript  avg session-start  avg lazy-path  avg content-read\n"
        "main                        1                        100                100              0                 0\n"
        "pc-core:reviewer            1                          0                  0              0                 0\n"
        "\n"
        "after\n"
        "actor             transcripts  avg rule bytes/transcript  avg session-start  avg lazy-path  avg content-read\n"
        "main                        1                         50                  0             10                40\n"
        "pc-core:reviewer            1                          0                  0              0                 0\n"
        "\n"
        "session-start = injected at session start (rule bodies and lazy stubs)\n"
        "\n"
        "delta (after − before)\n"
        "actor             before  after  delta bytes  delta %\n"
        "main                 100     50          -50   -50.0%\n"
        "pc-core:reviewer       0      0           +0      n/a\n"
        "\n"
        "rules loaded in after window\n"
        "main\n"
        "  t.md  1\n"
        "pc-core:reviewer\n"
        "  none\n"
        "\n"
        "summary: pc-core:reviewer avg rule bytes before=0 after=0\n"
    )


def test_header_line_defines_session_start(tmp_path, capsys):
    _write(tmp_path / "pinky-x" / "s.jsonl", [_msg("2026-09-20T10:00:00Z")])
    out = _report(tmp_path, capsys)
    assert (
        "session-start = injected at session start (rule bodies and lazy stubs)\n"
        in out
    )


def test_subagent_without_meta_is_unknown(tmp_path):
    proj = tmp_path / "pinky-x"
    base = proj / "s1" / "subagents"
    _write(base / "agent-a.jsonl", [_msg("2026-09-20T10:00:00Z")])
    assert [a for a, _ in rlr.subagent_transcripts(proj / "s1")] == ["unknown"]


def test_main_rejects_bad_bound(tmp_path):
    with pytest.raises(SystemExit):
        rlr.main(["--projects-dir", str(tmp_path), "--before", "garbage"])
