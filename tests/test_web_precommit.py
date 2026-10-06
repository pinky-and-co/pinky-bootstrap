"""Web pre-commit extra — detection, assembly, and hook behaviour.

A web repo (package.json, no
pyproject) gets `extras/web.yaml`; the four JS/HTML hooks all block.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

HOOKS = setup.CORE_HOOKS_DIR


def _run(script: str, *args: str, cwd: Path | None = None) -> int:
    return subprocess.run(
        [sys.executable, str(HOOKS / script), *args], cwd=cwd
    ).returncode


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_resolve_extras_web_when_package_json_no_pyproject(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert setup.resolve_extras(tmp_path) == ["web"]


def test_resolve_extras_python_wins_when_both_present(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
    assert setup.resolve_extras(tmp_path) == ["python"]


def test_resolve_extras_empty_for_bare_repo(tmp_path):
    assert setup.resolve_extras(tmp_path) == []


def test_web_config_includes_all_four_hooks(tmp_path):
    cfg = setup.build_precommit_config(tmp_path, ["web"])
    for pcid in ("js-file-size", "js-structure", "html-inline-js", "js-engine-sync"):
        assert f"id: {pcid}" in cfg


def test_hook_files_python_repo_excludes_web_scripts(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='x'\ndependencies=[]", encoding="utf-8"
    )
    names = {f.name for f in setup._hook_files(tmp_path)}
    assert "check_typed_api.py" in names
    for web_script in ("check_js_engine_sync.py", "check_html_inline_js.py"):
        assert web_script not in names


def test_hook_files_web_repo_excludes_python_scripts(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    names = {f.name for f in setup._hook_files(tmp_path)}
    assert "check_js_engine_sync.py" in names
    assert "check_typed_api.py" not in names


def test_hook_files_tool_directives_always_included(tmp_path):
    names = {f.name for f in setup._hook_files(tmp_path)}
    assert "tool_directives.py" in names


def test_hook_files_report_renderer_always_included(tmp_path):
    names = {f.name for f in setup._hook_files(tmp_path)}
    assert "_report.py" in names


def test_hook_files_generate_ci_badges_always_included(tmp_path):
    names = {f.name for f in setup._hook_files(tmp_path)}
    assert "generate_ci_badges.py" in names


def test_js_engine_sync_blocks_when_min_missing(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    eng = tmp_path / "engine.js"
    eng.write_text("export const f = () => 1;\n", encoding="utf-8")
    _git("add", "engine.js", cwd=tmp_path)
    assert _run("check_js_engine_sync.py", "engine.js", cwd=tmp_path) == 1


def test_js_engine_sync_passes_when_min_staged(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    eng = tmp_path / "engine.js"
    mins = tmp_path / "engine.min.js"
    eng.write_text("x", encoding="utf-8")
    mins.write_text("x", encoding="utf-8")
    _git("add", "engine.js", "engine.min.js", cwd=tmp_path)
    assert (
        _run("check_js_engine_sync.py", "engine.js", "engine.min.js", cwd=tmp_path) == 0
    )


def test_web_hooks_block(tmp_path):
    big = tmp_path / "app.js"
    big.write_text("// line\n" * 300, encoding="utf-8")
    html = tmp_path / "index.html"
    html.write_text("<script>alert(1)</script>", encoding="utf-8")
    assert _run("check_js_file_size.py", str(big)) == 1
    assert _run("check_js_structure.py", str(big)) == 1
    assert _run("check_html_inline_js.py", str(html)) == 1


def test_html_inline_js_ignores_jsonld_schema(tmp_path):
    html = tmp_path / "index.html"
    html.write_text(
        '<script type="application/ld+json">{"@type":"Product"}</script>',
        encoding="utf-8",
    )

    out = subprocess.run(
        [sys.executable, str(HOOKS / "check_html_inline_js.py"), str(html)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert out.returncode == 0
    assert "HTML-JS" not in out.stdout


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q"]))
