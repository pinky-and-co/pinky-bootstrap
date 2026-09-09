"""`plugin-repo` extra — the manifest/vendor gates it owns, and the quality-gate scope a plugin
repo's *full* config (python + plugin-repo) resolves to.

Card `agents-provider-routing-offline-adversarial.md` (chantier 0023) once needed a narrower copy
of the `python` extra's hooks here because that extra was hardcoded to `^src/`. `_py_lint_roots`
now derives the scope (chantier 0024), so the `python` extra covers `^plugins/` for a plugin repo
and this extra carries only what has no other home.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

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
    """Card `declarer-dependencies-plugin-et-valider-strict.md` (chantier 0023): every plugin repo
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
    consumers = [
        t
        for targets in setup.VENDOR_MAP.values()
        for t in targets
        if "/pc-core/" not in t
    ]
    assert consumers and all(Path(t).name.startswith("pc_") for t in consumers), (
        f"every non-pc-core vendored copy must be plugin-prefixed: {consumers}"
    )


def test_check_vendor_checksum_hook_present(tmp_path):
    """Card `decouper-pc-core-en-pc-git-et-pc-kanban.md` (chantier 0023): a vendored file
    (policy_lib.py, secret_patterns.py, …) must be checked against its source checksum at commit
    time."""
    cfg = _plugin_repo_config(tmp_path)
    assert "id: check-vendor-checksum" in cfg
    assert "scripts/hooks/check_vendor_checksum.py" in cfg
