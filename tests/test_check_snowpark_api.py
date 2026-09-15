"""check_snowpark_api.py — a stored procedure is called through session.call(), never session.sql("CALL …")."""

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "check_snowpark_api.py"

_spec = importlib.util.spec_from_file_location("check_snowpark_api", HOOK)
csa = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = (
    csa  # dataclasses needs its module registered to resolve KW_ONLY (py3.12)
)
_spec.loader.exec_module(csa)


def _check(src: str, tmp_path: Path) -> list[tuple[int, str]]:
    f = tmp_path / "sample.py"
    f.write_text(src, encoding="utf-8")
    return csa.check_file(f)


def _call_msg(proc: str) -> str:
    return (
        f'session.sql("CALL {proc} …") — use session.call("{proc}", *args); '
        'pass a SQL expression argument as a Column: call_function("NAME", lit(value)). '
        "No # pinky: marker suppresses this"
    )


def test_static_call_names_session_call(tmp_path):
    src = 'session.sql("CALL MY_DB.S.PROC(1)").collect()\n'
    assert _check(src, tmp_path) == [(1, _call_msg("MY_DB.S.PROC"))]


def test_call_is_not_suppressed_by_any_pinky_marker(tmp_path):
    src = (
        "session.sql(  # pinky: SNOWPARK-API  # pinky: SNOWPARK-SQL-INLINE\n"
        '    "CALL SYSTEM$SEND_SNOWFLAKE_NOTIFICATION("\n'
        '    "  SNOWFLAKE.NOTIFICATION.TEXT_PLAIN("\n'
        '    "    SNOWFLAKE.NOTIFICATION.SANITIZE_WEBHOOK_CONTENT(?)"\n'
        '    "  ),"\n'
        '    "  SNOWFLAKE.NOTIFICATION.INTEGRATION(?)"\n'
        '    ")",\n'
        "    params=[message, integration],\n"
        ").collect()\n"
    )
    assert _check(src, tmp_path) == [
        (1, _call_msg("SYSTEM$SEND_SNOWFLAKE_NOTIFICATION"))
    ]


def test_interpolated_procedure_name_still_flagged(tmp_path):
    src = 'session.sql(f"CALL {schema}.FEED_LOOP(1)")  # pinky: SNOWPARK-SQL-INLINE\n'
    assert _check(src, tmp_path) == [(1, _call_msg("<procedure>"))]


def test_lowercase_call_is_flagged(tmp_path):
    src = 'session.sql("  call my_proc(1)")  # pinky: SNOWPARK-API\n'
    assert _check(src, tmp_path) == [(1, _call_msg("my_proc"))]


def test_marked_select_stays_suppressed(tmp_path):
    src = 'session.sql("SELECT 1")  # pinky: SNOWPARK-API\n'
    assert _check(src, tmp_path) == []


def test_non_snowpark_receiver_is_ignored(tmp_path):
    src = 'cursor.sql("CALL MY_PROC()")\n'
    assert _check(src, tmp_path) == []


def test_call_blocks_the_commit(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text('session.sql("CALL P()")  # pinky: SNOWPARK-API\n', encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(HOOK), str(f)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 1
    assert run.stdout.splitlines()[0] == f"❌ [SNOWPARK-API] {f}:1: {_call_msg('P')}"
