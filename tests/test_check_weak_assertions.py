"""check_weak_assertions.py — the cliquet against fragment-only assertions on generated output.

Defines "done" for the chantier-0001 card `hook-cliquet-weak-assertions` (stage 3 of the
tests.md § generator-oracle pattern). Covers the narrow audit-validated heuristic AND the three
detection bugs the purge audit already paid (scripts/hooks copies, private-name variants, oracle
routed through a helper), plus the DoD mutation: reintroducing `assert "MY_DAG" in clause` blocks.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOK = setup.CORE_HOOKS_DIR / "check_weak_assertions.py"

_spec = importlib.util.spec_from_file_location("check_weak_assertions", HOOK)
cwa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cwa)


def _check(
    src: str, tmp_path: Path, name: str = "test_sample.py"
) -> list[tuple[int, str]]:
    f = tmp_path / name
    f.write_text(src, encoding="utf-8")
    return cwa.check_file(f)


def test_flags_fragment_in_without_oracle(tmp_path):
    src = (
        "def test_x():\n"
        "    clause = build_when_clause(task)\n"
        '    assert "MY_DAG" in clause\n'
    )
    out = _check(src, tmp_path)
    assert out == [(3, "build_when_clause")]


def test_flags_direct_generator_call_as_container(tmp_path):
    src = 'def test_x():\n    assert "<div" in render_page(ctx)\n'
    assert _check(src, tmp_path) == [(2, "render_page")]


def test_equality_oracle_in_same_file_exempts(tmp_path):

    src = (
        "def test_frag():\n"
        "    clause = build_when_clause(task)\n"
        '    assert "MY_DAG" in clause\n'
        "def test_oracle():\n"
        "    assert build_when_clause(task) == \"SYSTEM$...('MY_DAG$ROOT') != 'SKIP'\"\n"
    )
    assert _check(src, tmp_path) == []


def test_oracle_in_sibling_file_exempts_repo_wide(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    frag = tests_dir / "test_frag.py"
    frag.write_text(
        'def test():\n    c = build_sql(q)\n    assert "SELECT" in c\n',
        encoding="utf-8",
    )
    (tests_dir / "test_oracle.py").write_text(
        'def test():\n    assert build_sql(q) == "SELECT 1"\n', encoding="utf-8"
    )

    assert _run(str(frag)) == 0

    assert cwa.check_file(frag) == [(3, "build_sql")]


def test_oracle_routed_through_helper_exempts(tmp_path):

    src = (
        "def _assert_golden(name, actual):\n"
        "    expected = _load(name)\n"
        "    assert actual == expected\n"
        "def test_html():\n"
        "    html = generate_html(ctx)\n"
        '    assert "<div" in html\n'
        '    _assert_golden("generate_html_basic", html)\n'
    )
    assert _check(src, tmp_path) == []


def test_not_in_is_exempt(tmp_path):

    src = 'def test_x():\n    assert "EXPIRE AFTER" not in build_ddl(policy)\n'
    assert _check(src, tmp_path) == []


def test_non_generator_name_is_the_assumed_hole(tmp_path):
    src = 'def test_x():\n    assert "<td" in dl_card(row)\n'
    assert _check(src, tmp_path) == []


def test_non_string_left_operand_ignored(tmp_path):

    src = 'def test_x():\n    key = "k"\n    assert key in build_query(spec)\n'
    assert _check(src, tmp_path) == []


def test_private_name_variant_is_matched(tmp_path):

    src = 'def test_x():\n    ddl = _build_ddl(spec)\n    assert "CREATE" in ddl\n'
    assert _check(src, tmp_path) == [(3, "_build_ddl")]


def test_scripts_hooks_copies_are_excluded(tmp_path):
    d = tmp_path / "scripts" / "hooks"
    d.mkdir(parents=True)
    f = d / "check_x.py"
    f.write_text('def test():\n    assert "x" in build_sql(q)\n', encoding="utf-8")
    assert cwa.check_file(f) == []


def _run(*args: str) -> int:
    return subprocess.run([sys.executable, str(HOOK), *args]).returncode


def test_mutation_reintroducing_a_fragment_assert_blocks(tmp_path):
    weak = tmp_path / "test_weak.py"
    weak.write_text(
        'def test():\n    clause = build_when_clause(t)\n    assert "MY_DAG" in clause\n',
        encoding="utf-8",
    )
    assert _run(str(weak)) == 1


def test_oracle_covered_file_exits_clean(tmp_path):
    ok = tmp_path / "test_ok.py"
    ok.write_text(
        'def test():\n    assert build_when_clause(t) == "full expected string"\n',
        encoding="utf-8",
    )
    assert _run(str(ok)) == 0


def test_disabled_via_env_returns_zero(tmp_path, monkeypatch):
    weak = tmp_path / "test_weak.py"
    weak.write_text(
        'def test():\n    c = build_sql(q)\n    assert "SELECT" in c\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PINKY_DISABLED_HOOKS", "check_weak_assertions")
    assert _run(str(weak)) == 0
