"""`plugin-repo` extra — the manifest/vendor gates it owns, and the quality-gate scope a plugin
repo's *full* config (python + plugin-repo) resolves to.

`_py_lint_roots` derives the scope from the repo's own layout, so the `python` extra covers
`^plugins/` for a plugin repo and this extra carries only what has no other home.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup

QUALITY_HOOK_IDS = ("mypy", "bandit", "interrogate", "darglint", "check-typed-api")


def _plugin_repo_config(tmp_path: Path) -> str:
    return setup.build_precommit_config(tmp_path, ["plugin-repo"])


def _full_plugin_repo_config(tmp_path: Path) -> str:
    """A realistic plugin repo: `plugins/<p>/hooks/<f>.py` present (so `_py_lint_roots` finds
    `plugins/`), python + plugin-repo extras — the pair `resolve_extras` returns for one with a
    `pyproject.toml`."""
    f = tmp_path / "plugins" / "pc-x" / "hooks" / "thing.py"
    f.parent.mkdir(parents=True)
    f.write_text("", encoding="utf-8")
    return setup.build_precommit_config(tmp_path, ["python", "plugin-repo"])


def test_quality_hooks_cover_all_plugin_python_via_python_extra(tmp_path):
    """The `python` extra resolves to `^plugins/` — a superset of hooks/ + mcp/ + skills/scripts/ —
    so every quality hook covers a plugin repo's own Python."""
    cfg = _full_plugin_repo_config(tmp_path)
    for hook_id in QUALITY_HOOK_IDS:
        assert f"id: {hook_id}" in cfg
    assert "files: ^plugins/\n" in cfg or "^plugins/" in cfg


def test_quality_hooks_are_not_duplicated_by_the_plugin_repo_extra(tmp_path):
    """The narrower `plugins/*/hooks|mcp` copy is gone — each hook runs once, not twice."""
    cfg = _full_plugin_repo_config(tmp_path)
    for hook_id in QUALITY_HOOK_IDS:
        assert cfg.count(f"id: {hook_id}\n") == 1, f"{hook_id} appears more than once"
    files_lines = [
        ln.strip() for ln in cfg.splitlines() if ln.strip().startswith("files:")
    ]
    assert not any("(hooks|mcp)/" in ln for ln in files_lines)


def test_validate_plugins_strict_hook_present(tmp_path):
    """Every plugin repo
    must run `claude plugin validate --strict` on its own manifests as a commit-time gate."""
    cfg = _plugin_repo_config(tmp_path)
    assert "id: validate-plugins-strict" in cfg
    assert "scripts/hooks/validate_plugins_strict.py" in cfg


def test_mypy_collisions_solved_by_naming_not_exclusion(tmp_path):
    """mypy hard-errors 'Duplicate module named X' when one invocation sees two same-basename files
    under sibling plugins/*/ dirs. The fix is unique filenames at the source (VENDOR_MAP targets are
    `pc_<plugin>_<name>.py`, MCP entrypoints `<plugin>_server.py`), not a per-file `exclude:` that
    would silently drop coverage."""
    cfg = _full_plugin_repo_config(tmp_path)
    collision_markers = (
        "policy_lib",
        "secret_patterns",
        "plugin_scope_lib",
        "server\\.py",
    )
    exclude_lines = [
        ln.strip() for ln in cfg.splitlines() if ln.strip().startswith("exclude:")
    ]
    assert not any(m in ln for ln in exclude_lines for m in collision_markers), (
        "no exclude may name a same-basename collision — those are solved by per-plugin naming"
    )
    consumers = [t for targets in setup.VENDOR_MAP.values() for t in targets[1:]]
    assert consumers and all(Path(t).name.startswith("pc_") for t in consumers), (
        f"every non-home vendored copy must be plugin-prefixed: {consumers}"
    )


def test_vendor_map_homes_the_bootstrap_libs_in_pc_autodiscovery():
    """`plugin_scope_lib` and `pending_user_action` bootstrap plugin activation itself, so they
    cannot sit in `pc-core` (not loaded until it is bootstrapped) — their home is `pc-autodiscovery`.
    `plugin_scope_lib` also reaches the spawn-workers skill, which enables the matched plugins
    before a worker session starts."""
    assert setup.VENDOR_MAP["plugin_scope_lib.py"] == [
        "plugins/pc-autodiscovery/hooks/plugin_scope_lib.py",
        "plugins/pc-kanban/skills/chantier/scripts/pc_kanban_plugin_scope_lib.py",
        "plugins/pc-kanban/skills/spawn-workers/scripts/pc_kanban_spawn_plugin_scope_lib.py",
    ]
    assert setup.VENDOR_MAP["pending_user_action.py"] == [
        "plugins/pc-autodiscovery/hooks/pending_user_action.py",
        "plugins/pc-kanban/skills/chantier/scripts/pc_kanban_pending_user_action.py",
    ]


def test_check_vendor_checksum_regex_covers_the_spawn_workers_copy(tmp_path):
    """An edit to `pc_kanban_spawn_plugin_scope_lib.py` must trip the checksum gate like any other
    vendored copy."""
    assert "pc_kanban_spawn_plugin_scope_lib" in _plugin_repo_config(tmp_path)


def test_check_vendor_checksum_hook_present(tmp_path):
    """A vendored file
    (policy_lib.py, secret_patterns.py, …) must be checked against its source checksum at commit
    time."""
    cfg = _plugin_repo_config(tmp_path)
    assert "id: check-vendor-checksum" in cfg
    assert "scripts/hooks/check_vendor_checksum.py" in cfg
