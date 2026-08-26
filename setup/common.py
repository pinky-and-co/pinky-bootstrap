"""Shared paths — base layer for the setup package.

No imports from sibling setup/* modules (precommit.py, cli.py all depend on this one, never the
other way).
"""

import os
import sys
import tomllib
from importlib import metadata
from pathlib import Path

PROVIDERS = ["claude", "mistral"]

# This package lives at <workspace-root>/pinky-workspace/setup/ — one level deeper than the
# former setup.py, so SCRIPT_DIR (= pinky-workspace/) needs the extra .parent to stay correct.
PACKAGE_DIR = Path(__file__).parent.resolve()
SCRIPT_DIR = PACKAGE_DIR.parent

# ── Workspace root — resolved, NEVER derived from the install path (ADR-0065) ─────────────────
# WORKSPACE_ROOT used to be `SCRIPT_DIR.parent`, i.e. "whatever sits above wherever this code was
# unpacked". That only ever worked because the moteur is cloned INSIDE the workspace it serves.
# Installed anywhere else (`uv tool install`, a pipx venv, site-packages), the same expression
# points at the install prefix — and discover_repos(), which globs WORKSPACE_ROOT, then scans
# site-packages and finds zero repos. Nothing failed loudly; the distribution simply became a no-op.
#
# So the workspace announces ITSELF — by the nearest `*.code-workspace` file above the CURRENT
# DIRECTORY, the VSCode multi-root convention that already exists wherever this moteur runs — and
# the moteur finds it by walking up. No bespoke marker to create or maintain.
WORKSPACE_ROOT_ENV = "PINKY_WORKSPACE_ROOT"


def find_workspace_root(start: Path) -> Path:
    """Workspace root — env ``PINKY_WORKSPACE_ROOT`` > nearest ``*.code-workspace`` above `start` > legacy.

    Args:
        start: Directory to walk up from — the caller's current directory in practice.

    Returns:
        The resolved workspace root. Falls back to ``SCRIPT_DIR.parent`` (the pre-ADR-0065
        behaviour) when no ``*.code-workspace`` file is found, so a moteur cloned inside its
        workspace keeps working with nothing configured.
    """
    env = os.environ.get(WORKSPACE_ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    start = start.resolve()
    for base in [start, *start.parents]:
        if any(p.is_file() for p in base.glob("*.code-workspace")):
            return base
    return SCRIPT_DIR.parent


WORKSPACE_ROOT = find_workspace_root(Path.cwd())

# Two source roots, split by what they are — not one `core/` mixing both (2026-08-20 reorg):
# agentic-harness/ = content a Claude Code session loads (rules, status-lines) ; hygiene/ = non-
# agentic repo tooling (ci, hooks, pre-commit) this CLI distributes into consumer repos.
AGENTIC_HARNESS_DIR = SCRIPT_DIR / "agentic-harness"
HYGIENE_DIR = SCRIPT_DIR / "hygiene"

# ── Hooks distribution (hygiene/ = single source) ────────────────────────────
CORE_HOOKS_DIR = HYGIENE_DIR / "hooks"
# Harness (Claude Code) hooks — distinct from the git pre-commit hooks in CORE_HOOKS_DIR.
# Installed to <claude_dir>/scripts/ and wired into settings.json (see _install_status_lines).
CORE_HARNESS_HOOKS_DIR = AGENTIC_HARNESS_DIR / "status-lines"
CORE_PRECOMMIT_DIR = HYGIENE_DIR / "pre-commit"
CORE_CI_DIR = HYGIENE_DIR / "ci"
# Small utility modules shared by two plugins that end up split apart by the plugin boundary
# (a plugin can only ever import its own files — no relative reach into a `dependencies` entry).
# Vendored here rather than duplicated by hand so both copies stay provably identical.
CORE_VENDOR_DIR = HYGIENE_DIR / "vendor"

# render_docs.py renders the repo-local README/index.md sections (badges/tagline/documentation/
# license). It is distributed as-is into every repo's scripts/hooks/ so the `generate-docs` commit
# hook can run it without the full workspace — importing it here too means setup.py and the hook
# share one render implementation, never two (see the generate-docs-hook kanban card).
sys.path.insert(0, str(CORE_HOOKS_DIR))
from render_docs import (  # noqa: E402
    SuiteIdentity,
    has_generated_index,
    inject_readme_sections_local,
    render_index_home,
    render_readme_why,
)


# ── Engine version — never derived from git (card `versionner-le-moteur`) ─────────────────────
# `importlib.metadata` reads the installed distribution's own metadata (written by hatchling from
# pyproject.toml's `version` at build time) — the only source that works once the moteur is
# `uv tool install`-ed and SCRIPT_DIR points inside a venv, not a checkout. Falls back to parsing
# `pyproject.toml` straight off disk for the still-common case this repo is itself run from: a
# plain clone via `python3 setup.py`, never `pip install`-ed, so there is no distribution to query.
def engine_version() -> str:
    """The moteur's own version, from installed package metadata or its own `pyproject.toml`."""
    try:
        return metadata.version("pinky-bootstrap")
    except metadata.PackageNotFoundError:
        data = tomllib.loads(
            (SCRIPT_DIR / "pyproject.toml").read_text(encoding="utf-8")
        )
        return data["project"]["version"]


__all__ = [
    "PROVIDERS",
    "PACKAGE_DIR",
    "SCRIPT_DIR",
    "WORKSPACE_ROOT",
    "WORKSPACE_ROOT_ENV",
    "find_workspace_root",
    "AGENTIC_HARNESS_DIR",
    "HYGIENE_DIR",
    "CORE_HOOKS_DIR",
    "CORE_HARNESS_HOOKS_DIR",
    "CORE_PRECOMMIT_DIR",
    "CORE_CI_DIR",
    "engine_version",
    "SuiteIdentity",
    "inject_readme_sections_local",
    "has_generated_index",
    "render_index_home",
    "render_readme_why",
]
