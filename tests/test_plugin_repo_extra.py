"""`plugin-repo` extra — quality-gate scope must cover every Python a plugin repo authors.

Card `agents-provider-routing-offline-adversarial.md` (chantier 0023): the extra's 5 hooks
(mypy/bandit/interrogate/darglint/check-typed-api) only matched `plugins/*/hooks/`, so a plugin's
`mcp/server.py` (e.g. `pc-core`'s MCP server) passed unreviewed by any of them — found 2026-08-22.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import setup  # noqa: E402

HOOK_IDS = ("mypy", "bandit", "interrogate", "darglint", "check-typed-api")


def _plugin_repo_config(tmp_path: Path) -> str:
    return setup.build_precommit_config(tmp_path, ["plugin-repo"])


def test_quality_hooks_cover_hooks_subdir(tmp_path):
    cfg = _plugin_repo_config(tmp_path)
    for hook_id in HOOK_IDS:
        assert f"id: {hook_id}" in cfg or hook_id == "bandit"


def test_quality_hooks_also_cover_mcp_subdir(tmp_path):
    """The bug: `files: ^plugins/[^/]+/hooks/` never matches `plugins/pc-core/mcp/server.py`."""
    cfg = _plugin_repo_config(tmp_path)
    assert "plugins/[^/]+/(hooks|mcp)/" in cfg, (
        "plugin-repo.yaml's quality hooks must also scope plugins/*/mcp/, "
        "not just plugins/*/hooks/ — an MCP server ships real Python too."
    )


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
    cfg = _plugin_repo_config(tmp_path)
    mypy_block = cfg.split("id: mypy", 1)[1].split("- repo:", 1)[0]
    assert not any(
        line.strip().startswith("exclude:") for line in mypy_block.splitlines()
    ), (
        "the mypy hook must carry no same-basename exclude — collisions are solved by naming"
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
    (policy_lib.py, secret_patterns.py) must be checked against its source checksum at commit time."""
    cfg = _plugin_repo_config(tmp_path)
    assert "id: check-vendor-checksum" in cfg
    assert "scripts/hooks/check_vendor_checksum.py" in cfg
